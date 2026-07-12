"""Opportunity Engine: the deterministic capstone that unifies every module's
recommendations into one prioritized, context-gated, deduplicated view.

It calls the five deterministic analyzers (Content Intelligence, Review
Intelligence, AI Query Signals, AI Visibility, Competitor Intelligence),
normalizes their different recommendation shapes into one, applies a consistent
Property Context gate pass so gating is uniform across sources, boosts
opportunities that more than one independent module points at (corroboration),
and ranks the result. No LLM; identical inputs always produce the identical
ranked list, and Suppressed / insufficient-data items are surfaced honestly in
their own buckets rather than hidden.
"""

import re
from datetime import date

from sqlalchemy.orm import Session

from app.connectors.development import DevelopmentDataProvider
from app.models import Property
from app.services.ai_query_signals import analyze_ai_query_signals
from app.services.ai_visibility import analyze_ai_visibility
from app.services.competitor_intelligence import analyze_share_of_voice
from app.services.content_intelligence import analyze_property
from app.services.property_context import (
    REGULATED,
    SUPPRESSED,
    UNKNOWN,
    gate_text,
    get_property_context,
)
from app.services.review_intelligence import analyze_property_reviews

SOURCE_LABELS = {
    "content": "Content IQ",
    "reviews": "Review IQ",
    "ai_query_signals": "AI Query Signals",
    "ai_visibility": "AI Visibility",
    "competitors": "Competitor IQ",
}

STATE_WEIGHT = {
    "Actionable": 4,
    "Requires confirmation": 3,
    "Monitor": 2,
    "Insufficient data": 1,
    "Suppressed": 0,
}
IMPACT_RANK = {"High": 3, "Medium": 2, "Low": 1}
EFFORT_PENALTY = {"Low": 0, "Medium": 1, "High": 2}

# Topic keywords used only to detect when independent modules point at the same
# thing (corroboration). Deterministic substring set; extend freely.
_TOPIC_KEYWORDS = (
    "parking", "pet", "pricing", "price", "availability", "amenit", "neighborhood",
    "maintenance", "lease", "faq", "floor plan", "pool", "fitness", "school",
    "transportation", "content", "review", "reputation", "visibility",
    "competitor", "engagement", "landing page", "search", "seo", "eligibility",
    "affordab",
)

SENSITIVE_KEYWORDS = (
    "pricing", "price", "availab", "afford", "income", "eligib", "voucher",
    "special", "concession", "luxury", "student", "senior", "military",
    "young professional", "exclusive",
)
REQUIRES_CONFIRMATION_MSG = (
    "This touches price, eligibility, or audience positioning. Confirm approved "
    "property messaging before acting on it."
)


def _keywords(text: str) -> set[str]:
    low = text.lower()
    return {k for k in _TOPIC_KEYWORDS if k in low}


def _norm(source: str, item: dict) -> dict:
    """Map a source module's recommendation onto the common Opportunity shape,
    tolerant of each module's differing keys."""
    title = (
        item.get("title")
        or item.get("suggested_action")
        or item.get("label")
        or "Recommended action"
    )
    reason = item.get("reason") or item.get("explanation") or ""
    if source == "reviews" and not reason:
        reason = (
            f"{item.get('negative_mentions', 0)} negative mention(s) of "
            f"{item.get('label', 'this theme')} (severity {item.get('severity_level', 'n/a')})."
        )
    return {
        "source": source,
        "source_label": SOURCE_LABELS[source],
        "title": title,
        "reason": reason,
        "state": item.get("state", "Actionable"),
        "impact": item.get("impact"),
        "effort": item.get("effort"),
        "evidence_level": item.get("evidence_level"),
        "citations": item.get("citations") or [],
        "gate_reason": item.get("gate_reason"),
    }


def _apply_gate(context: dict, opp: dict) -> dict:
    """Uniform gate pass so every source is gated the same way, even ones that
    did not attach a state (Content/Review opportunities). Never loosens an
    already-restrictive state."""
    if opp["state"] in ("Suppressed", "Requires confirmation", "Insufficient data"):
        return opp
    probe = f"{opp['title']} {opp['reason']}"
    gt = gate_text(context, probe)
    if gt.status == SUPPRESSED:
        opp["state"] = "Suppressed"
        opp["gate_reason"] = gt.reason
    elif any(k in probe.lower() for k in SENSITIVE_KEYWORDS) and context[
        "effective_regulatory"
    ] in (UNKNOWN, REGULATED):
        opp["state"] = "Requires confirmation"
        opp["gate_reason"] = opp["gate_reason"] or REQUIRES_CONFIRMATION_MSG
    return opp


def build_opportunities(
    db: Session,
    property_id: int,
    today: date | None = None,
    content_provider=None,
    review_provider=None,
) -> dict:
    today = today or date.today()
    prop = db.get(Property, property_id)
    if prop is None:
        raise ValueError("Property not found.")
    content_provider = content_provider or DevelopmentDataProvider()
    review_provider = review_provider or DevelopmentDataProvider()
    context = get_property_context(db, property_id)

    raw: list[dict] = []

    def collect(source: str, items):
        for item in items or []:
            raw.append(_apply_gate(context, _norm(source, item)))

    # Each analyzer is guarded: an empty or not-yet-usable module contributes
    # nothing rather than breaking the unified view.
    try:
        ci = analyze_property(db, property_id, today=today, content_provider=content_provider)
        collect("content", ci.get("opportunities"))
    except Exception:
        pass
    try:
        ri = analyze_property_reviews(db, property_id, review_provider=review_provider)
        collect("reviews", ri.get("opportunities"))
    except Exception:
        pass
    try:
        aqs = analyze_ai_query_signals(db, property_id, content_provider=content_provider)
        collect("ai_query_signals", aqs.get("recommendations"))
    except Exception:
        pass
    try:
        av = analyze_ai_visibility(db, property_id, today=today)
        collect("ai_visibility", av.get("recommendations"))
    except Exception:
        pass
    try:
        comp = analyze_share_of_voice(db, property_id, today=today)
        collect("competitors", comp.get("recommendations"))
    except Exception:
        pass

    # Corroboration: which distinct sources touch each topic keyword.
    keyword_sources: dict[str, set[str]] = {}
    for opp in raw:
        opp["_keywords"] = _keywords(f"{opp['title']} {opp['reason']}")
        for k in opp["_keywords"]:
            keyword_sources.setdefault(k, set()).add(opp["source"])

    for opp in raw:
        corr_sources: set[str] = set()
        for k in opp["_keywords"]:
            corr_sources |= keyword_sources.get(k, set())
        corr_sources.discard(opp["source"])
        opp["corroborating_sources"] = sorted(SOURCE_LABELS[s] for s in corr_sources)
        boost = len(corr_sources)
        impact = IMPACT_RANK.get(opp["impact"] or "Medium", 2)
        effort_pen = EFFORT_PENALTY.get(opp["effort"] or "Medium", 1)
        opp["priority_score"] = (
            STATE_WEIGHT.get(opp["state"], 1) * 100 + impact * 10 + boost * 5 - effort_pen
        )
        del opp["_keywords"]

    def rank(items):
        items.sort(
            key=lambda o: (-o["priority_score"], o["source"], o["title"])
        )
        for i, o in enumerate(items, start=1):
            o["priority"] = i
        return items

    actionable = rank([o for o in raw if o["state"] in ("Actionable", "Requires confirmation", "Monitor")])
    suppressed = [o for o in raw if o["state"] == "Suppressed"]
    insufficient = [o for o in raw if o["state"] == "Insufficient data"]

    by_source = {s: 0 for s in SOURCE_LABELS}
    for o in raw:
        by_source[o["source"]] += 1

    return {
        "property_id": property_id,
        "property_name": prop.name,
        "generated_on": today.isoformat(),
        "total": len(raw),
        "by_source": {SOURCE_LABELS[s]: n for s, n in by_source.items()},
        "opportunities": actionable,
        "suppressed": suppressed,
        "insufficient": insufficient,
        "summary": _summary(prop.name, actionable, suppressed, insufficient),
    }


def _summary(name, actionable, suppressed, insufficient) -> str:
    if not actionable and not suppressed and not insufficient:
        return (
            f"No recommendations yet for {name}. Add content, reviews, AI "
            "Visibility queries, or competitors to generate opportunities."
        )
    top = actionable[0]["title"] if actionable else None
    parts = [f"{len(actionable)} actionable opportunit"
             f"{'y' if len(actionable) == 1 else 'ies'} for {name}"]
    if top:
        parts.append(f"top priority: {top}")
    if suppressed:
        parts.append(f"{len(suppressed)} suppressed by property context")
    if insufficient:
        parts.append(f"{len(insufficient)} awaiting more data")
    return "; ".join(parts) + "."


def opportunity_engine_summary_text(
    db: Session, property_id: int, content_provider=None, review_provider=None
) -> str | None:
    """Deterministic summary indexed as an `opportunity_engine` RAG chunk, so
    Nora answers 'what should we do first?' from the unified prioritized list."""
    analysis = build_opportunities(
        db, property_id, content_provider=content_provider, review_provider=review_provider
    )
    if analysis["total"] == 0:
        return None
    lines = [
        f"Prioritized opportunities for {analysis['property_name']} (unified "
        "across Content IQ, Review IQ, AI Query Signals, AI Visibility, and "
        "Competitor IQ).",
        analysis["summary"],
    ]
    for o in analysis["opportunities"][:8]:
        corr = (
            f" [reinforced by {', '.join(o['corroborating_sources'])}]"
            if o["corroborating_sources"]
            else ""
        )
        lines.append(
            f"{o['priority']}. [{o['source_label']}] {o['title']} "
            f"({o['state']}){corr}. {o['reason']}"
        )
    if analysis["suppressed"]:
        lines.append(
            "Suppressed by property context (not recommended): "
            + "; ".join(o["title"] for o in analysis["suppressed"][:5])
        )
    if analysis["insufficient"]:
        lines.append(
            "Awaiting more data before recommending: "
            + "; ".join(o["title"] for o in analysis["insufficient"][:5])
        )
    return "\n".join(lines)
