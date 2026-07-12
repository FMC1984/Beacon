"""Phase 12 - AI Visibility Scanner: deterministic analysis of the queries the
Phase 11.5 foundation stored.

No LLM, no embeddings - pure, explainable analysis of stored responses, exactly
like Content and Review Intelligence. Every visibility characterization is
sample-size gated (a thin query sample says "cannot determine", never a precise
percentage), recommendations are evidence-backed and pass the Property Context
gate(), and the hallucination-hook flags from Phase 11.5 are interpreted into
findings here (the hook is detection; this is interpretation).

Deliberately NOT built (documented deferrals, each needs external data Beacon
does not hold): prompt-volume / demand estimation, source-authority
cross-referencing against Google rankings, and competitor share-of-voice.
"""

from datetime import date

from sqlalchemy.orm import Session

from app.models import Property
from app.services.ai_visibility.hallucination import check_response_against_context
from app.services.ai_visibility.providers import read_queries
from app.services.ai_visibility.reference import (
    MIN_QUERIES_FOR_VISIBILITY,
    methodology,
    platform_label,
)
from app.services.property_context import (
    REGULATED,
    SUPPRESSED,
    UNKNOWN,
    gate_text,
    get_property_context,
)

DIRECTIONAL_CAVEAT = (
    "These are directional signals from a small sample of AI queries. LLM "
    "outputs vary by phrasing, session, and model version, so this is not a "
    "precise visibility percentage and a single query does not generalize."
)
REQUIRES_CONFIRMATION_MSG = (
    "This touches price, eligibility, or audience positioning. Confirm approved "
    "property messaging before acting on it."
)
SENSITIVE_KEYWORDS = (
    "pricing", "price", "availab", "afford", "income", "eligib", "voucher",
    "special", "concession", "luxury", "student", "senior", "military",
    "young professional", "exclusive",
)

DEFERRED = [
    "Prompt-volume / demand estimation (how many real users ask this) - needs a "
    "data partnership Beacon does not have.",
    "Source-authority cross-referencing (whether cited sources rank in Google) - "
    "needs external ranking infrastructure.",
    "Competitor share-of-voice (your mentions vs competitors') - needs the "
    "Competitor Intelligence phase.",
]

WEIGHTS = {"mention": 0.6, "fact_consistency": 0.4}


def _grade(value: float) -> str:
    if value < 40:
        return "Poor"
    if value < 60:
        return "Basic"
    if value < 80:
        return "Good"
    return "Excellent"


def _domain_of_url(url: str | None) -> str | None:
    if not url:
        return None
    import re

    host = re.sub(r"^https?://", "", url.strip(), flags=re.IGNORECASE)
    host = host.split("/", 1)[0].split("?", 1)[0].lower().rstrip(".")
    return host[4:] if host.startswith("www.") else host or None


def analyze_ai_visibility(
    db: Session, property_id: int, today: date | None = None
) -> dict:
    today = today or date.today()
    prop = db.get(Property, property_id)
    if prop is None:
        raise ValueError("Property not found.")
    records = read_queries(db, property_id)
    context = get_property_context(db, property_id)

    base = {
        "property_id": property_id,
        "property_name": prop.name,
        "methodology": methodology(),
        "directional_caveat": DIRECTIONAL_CAVEAT,
        "deferred": DEFERRED,
    }

    if not records:
        return {
            **base,
            "has_queries": False,
            "sample": {"total_queries": 0, "sufficient": False},
            "by_platform": [],
            "mention": None,
            "source_landscape": [],
            "own_site": None,
            "fact_checks": {"contradictions": [], "cannot_verify_count": 0},
            "score": None,
            "recommendations": [],
            "limitations": [
                "No AI Visibility queries have been run for this property yet. "
                "Run queries to characterize how it appears on AI platforms."
            ],
        }

    n = len(records)
    sufficient = n >= MIN_QUERIES_FOR_VISIBILITY
    dates = sorted(r.executed_at.date() for r in records)
    total_mentions = sum(1 for r in records if r.brand_mentioned)

    # Per-platform mention rate (gated per platform - a platform with too few
    # queries reports "insufficient", never a misleading rate).
    per_platform: dict[str, dict] = {}
    for r in records:
        p = per_platform.setdefault(
            r.platform, {"n": 0, "mentions": 0, "sources": {}}
        )
        p["n"] += 1
        p["mentions"] += 1 if r.brand_mentioned else 0
        for d in r.sources_cited or []:
            p["sources"][d] = p["sources"].get(d, 0) + 1
    by_platform = []
    for platform, p in sorted(per_platform.items()):
        enough = p["n"] >= MIN_QUERIES_FOR_VISIBILITY
        by_platform.append(
            {
                "platform": platform,
                "label": platform_label(platform),
                "queries": p["n"],
                "mentions": p["mentions"],
                "mention_rate": round(p["mentions"] / p["n"], 3) if enough else None,
                "mention_rate_status": "measured" if enough else "insufficient",
                "top_sources": [
                    {"domain": d, "count": c}
                    for d, c in sorted(p["sources"].items(), key=lambda kv: (-kv[1], kv[0]))[:8]
                ],
            }
        )

    # Overall mention characterization, sample-gated.
    mention = {
        "queries": n,
        "mentions": total_mentions,
        "rate": round(total_mentions / n, 3) if sufficient else None,
        "status": "measured" if sufficient else "insufficient",
        "explanation": (
            f"Brand detected in {total_mentions} of {n} responses "
            "(literal, negation-unaware text match)."
            if sufficient
            else f"Only {n} of the recommended {MIN_QUERIES_FOR_VISIBILITY} "
            "queries have been run; visibility cannot be determined yet."
        ),
    }

    # Source landscape: which domains the AI leans on, and how often. This is
    # the honest subset of "sources" - it does NOT cross-reference Google
    # rankings (deferred).
    landscape: dict[str, int] = {}
    for r in records:
        for d in r.sources_cited or []:
            landscape[d] = landscape.get(d, 0) + 1
    source_landscape = [
        {"domain": d, "cited_in_queries": c}
        for d, c in sorted(landscape.items(), key=lambda kv: (-kv[1], kv[0]))
    ]

    own_domain = _domain_of_url(getattr(prop, "website_url", None))
    if own_domain is None:
        own_site = {
            "domain": None,
            "status": "cannot_verify",
            "explanation": "No website URL is set for this property, so Beacon "
            "cannot tell whether the AI cites the property's own site.",
        }
    else:
        cited = landscape.get(own_domain, 0)
        own_site = {
            "domain": own_domain,
            "cited_in_queries": cited,
            "status": "cited" if cited else "not_cited",
            "explanation": (
                f"The property's own site ({own_domain}) was cited in {cited} of "
                f"{n} responses."
                if cited
                else f"The property's own site ({own_domain}) was not cited in "
                f"any of the {n} responses."
            ),
        }

    # Interpret the Phase 11.5 hallucination hook across every response.
    contradictions = []
    cannot_verify_count = 0
    for r in records:
        result = check_response_against_context(r.raw_response_text, prop, context)
        if not result["context_configured"]:
            cannot_verify_count += 1
        for flag in result["flags"]:
            contradictions.append(
                {
                    "query_id": r.query_id,
                    "platform": r.platform,
                    "field": flag["field"],
                    "known_value": flag["known_value"],
                    "evidence": flag["evidence"],
                }
            )
    fact_checks = {
        "contradictions": contradictions,
        "cannot_verify_count": cannot_verify_count,
    }

    score = _score(mention, contradictions, sufficient)
    recommendations = _recommendations(
        context, sufficient, n, mention, own_site, contradictions
    )

    limitations = [DIRECTIONAL_CAVEAT]
    if not sufficient:
        limitations.append(
            f"Sample is below the {MIN_QUERIES_FOR_VISIBILITY}-query minimum; "
            "treat everything here as anecdotal."
        )

    return {
        **base,
        "has_queries": True,
        "analyzed_on": today.isoformat(),
        "date_range": {"start": dates[0].isoformat(), "end": dates[-1].isoformat()},
        "sample": {
            "total_queries": n,
            "sufficient": sufficient,
            "minimum": MIN_QUERIES_FOR_VISIBILITY,
        },
        "by_platform": by_platform,
        "mention": mention,
        "source_landscape": source_landscape,
        "own_site": own_site,
        "fact_checks": fact_checks,
        "score": score,
        "recommendations": recommendations,
        "limitations": limitations,
    }


def _score(mention: dict, contradictions: list, sufficient: bool) -> dict | None:
    """Explainable, and only when the sample clears the minimum. A thin sample
    gets no score (honest), never a fabricated percentage."""
    if not sufficient:
        return None
    mention_component = round((mention["rate"] or 0.0) * 100, 1)
    penalty = min(100, 25 * len(contradictions))
    fact_component = float(100 - penalty)
    value = (
        mention_component * WEIGHTS["mention"]
        + fact_component * WEIGHTS["fact_consistency"]
    )
    return {
        "value": round(value),
        "grade": _grade(value),
        "directional": True,
        "breakdown": [
            {
                "component": "mention_rate",
                "score": mention_component,
                "weight": WEIGHTS["mention"],
                "explanation": f"Brand mentioned in {mention['mentions']} of "
                f"{mention['queries']} responses.",
            },
            {
                "component": "fact_consistency",
                "score": fact_component,
                "weight": WEIGHTS["fact_consistency"],
                "explanation": f"{len(contradictions)} factual contradiction(s) "
                "detected against Beacon's known property data "
                f"({25} points each).",
            },
        ],
    }


def _gate(context: dict, text: str) -> tuple[str | None, str | None]:
    """Positioning themes can be suppressed; price/eligibility/audience topics
    require confirmation when the property is regulated or its status unknown."""
    gt = gate_text(context, text)
    if gt.status == SUPPRESSED:
        return "Suppressed", gt.reason
    if any(kw in text.lower() for kw in SENSITIVE_KEYWORDS) and context[
        "effective_regulatory"
    ] in (UNKNOWN, REGULATED):
        return "Requires confirmation", REQUIRES_CONFIRMATION_MSG
    return None, None


def _recommendations(
    context, sufficient, n, mention, own_site, contradictions
) -> list[dict]:
    recs = []

    def add(title, reason, base_state, evidence):
        block_state, block_reason = _gate(context, f"{title} {reason}")
        recs.append(
            {
                "title": title,
                "reason": reason,
                "state": block_state or base_state,
                "gate_reason": block_reason,
                "evidence": evidence,
            }
        )

    if not sufficient:
        recs.append(
            {
                "title": "Run more AI Visibility queries",
                "reason": f"Only {n} of the recommended {MIN_QUERIES_FOR_VISIBILITY} "
                "queries have been run. Run more before drawing conclusions.",
                "state": "Insufficient data",
                "gate_reason": None,
                "evidence": "sample size",
            }
        )
        return recs

    # Fact contradictions first - these are the most actionable and honest.
    for c in contradictions:
        add(
            f"Verify the AI's claim about {c['field'].replace('_', ' ')}",
            f"A response contradicted Beacon's known {c['field'].replace('_', ' ')} "
            f"({c['known_value']}): {c['evidence']} Confirm which is correct and "
            "correct the wrong one.",
            "Actionable",
            f"fact_check:{c['field']}",
        )

    if mention["rate"] == 0:
        add(
            "Improve how the property surfaces in AI answers",
            "The property was not mentioned in any of the sampled AI responses. "
            "Strengthen the site content and topics these prompts target.",
            "Actionable",
            "mention_rate:0",
        )
    elif mention["rate"] is not None and mention["rate"] < 0.5:
        add(
            "Increase AI-answer presence",
            f"The property appeared in {mention['mentions']} of {mention['queries']} "
            "responses. There is room to surface more consistently.",
            "Monitor",
            "mention_rate:low",
        )

    if own_site.get("status") == "not_cited":
        add(
            "Get the property's own site cited by AI answers",
            f"The AI cited other sources but not {own_site['domain']}. Ensure the "
            "site clearly and accurately covers the topics these prompts ask about.",
            "Monitor",
            "own_site:not_cited",
        )

    return recs
