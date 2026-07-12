"""Competitor Intelligence (Phase 13): deterministic AI-answer share of voice.

The one competitive question Beacon can answer HONESTLY today: across the AI
Visibility responses already collected for a property, how often does an AI
platform mention the property versus each operator-named competitor? Competitors
are operator-asserted (never discovered/scraped), mention detection reuses the
same literal, negation-unaware matching as brand detection, and every share
figure is sample-size gated exactly like AI Visibility.

Deliberately NOT built (declared, not silently skipped - each needs data Beacon
does not hold): automated competitor discovery, competitive pricing / occupancy,
and positioning / unit-mix comparison against competitor properties.
"""

from datetime import date

from sqlalchemy.orm import Session

from app.models import Competitor, Property
from app.services.ai_visibility.parsing import detect_mention
from app.services.ai_visibility.providers import read_queries
from app.services.ai_visibility.reference import MIN_QUERIES_FOR_VISIBILITY
from app.services.property_context import (
    REGULATED,
    SUPPRESSED,
    UNKNOWN,
    gate_text,
    get_property_context,
)

DIRECTIONAL_CAVEAT = (
    "Share of voice is directional, from a small sample of AI queries. LLM "
    "outputs vary by phrasing, session, and model version; this is not a precise "
    "market share and a single query does not generalize."
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
    "Automated competitor discovery - competitors are operator-named, never "
    "inferred or scraped by Beacon.",
    "Competitive pricing / occupancy comparison - Beacon holds no data on "
    "competitor properties.",
    "Positioning / unit-mix comparison - needs competitor property data Beacon "
    "does not have.",
]


def _terms(comp: Competitor) -> list[str]:
    return [comp.name] + [a for a in (comp.aliases or []) if a]


def _gate(context: dict, text: str) -> tuple[str | None, str | None]:
    gt = gate_text(context, text)
    if gt.status == SUPPRESSED:
        return "Suppressed", gt.reason
    if any(kw in text.lower() for kw in SENSITIVE_KEYWORDS) and context[
        "effective_regulatory"
    ] in (UNKNOWN, REGULATED):
        return "Requires confirmation", REQUIRES_CONFIRMATION_MSG
    return None, None


def analyze_share_of_voice(
    db: Session, property_id: int, today: date | None = None
) -> dict:
    today = today or date.today()
    prop = db.get(Property, property_id)
    if prop is None:
        raise ValueError("Property not found.")
    competitors = (
        db.query(Competitor)
        .filter_by(property_id=property_id)
        .order_by(Competitor.name)
        .all()
    )
    records = read_queries(db, property_id)
    context = get_property_context(db, property_id)

    base = {
        "property_id": property_id,
        "property_name": prop.name,
        "competitor_count": len(competitors),
        "directional_caveat": DIRECTIONAL_CAVEAT,
        "deferred": DEFERRED,
        "generated_on": today.isoformat(),
    }

    if not competitors:
        return {
            **base,
            "has_competitors": False,
            "has_ai_data": bool(records),
            "sample": {"total_queries": len(records), "sufficient": False},
            "share_of_voice": [],
            "recommendations": [],
            "limitations": [
                "No competitors are tracked for this property yet. Add the "
                "competitors you want compared (Beacon never guesses them)."
            ],
        }

    if not records:
        return {
            **base,
            "has_competitors": True,
            "has_ai_data": False,
            "sample": {"total_queries": 0, "sufficient": False},
            "share_of_voice": [],
            "recommendations": [],
            "limitations": [
                "No AI Visibility queries have been run for this property, so "
                "there is nothing to measure share of voice over. Run AI "
                "Visibility queries first."
            ],
        }

    n = len(records)
    sufficient = n >= MIN_QUERIES_FOR_VISIBILITY

    # Per-query PRESENCE (each entity counted once per query it appears in),
    # matching the brand_mentioned semantics. Deterministic literal matching.
    prop_count = 0
    comp_counts: dict[int, int] = {c.id: 0 for c in competitors}
    for r in records:
        text = r.raw_response_text
        if detect_mention(text, [prop.name]):
            prop_count += 1
        for c in competitors:
            if detect_mention(text, _terms(c)):
                comp_counts[c.id] += 1

    total = prop_count + sum(comp_counts.values())

    def share(count: int) -> float | None:
        if not sufficient or total == 0:
            return None
        return round(count / total, 3)

    entities = [
        {
            "name": prop.name,
            "is_property": True,
            "mentions": prop_count,
            "share": share(prop_count),
        }
    ] + [
        {
            "name": c.name,
            "is_property": False,
            "competitor_id": c.id,
            "mentions": comp_counts[c.id],
            "share": share(comp_counts[c.id]),
        }
        for c in competitors
    ]
    entities.sort(key=lambda e: (-e["mentions"], not e["is_property"], e["name"]))

    share_of_voice = {
        "queries": n,
        "sufficient": sufficient,
        "total_mentions": total,
        "status": "measured" if (sufficient and total > 0) else "insufficient",
        "entities": entities,
        "explanation": (
            f"Across {n} AI responses, the property was mentioned {prop_count} "
            f"time(s); competitor mentions are counted the same way (once per "
            "response they appear in)."
            if sufficient
            else f"Only {n} of the recommended {MIN_QUERIES_FOR_VISIBILITY} "
            "queries have been run; share of voice cannot be determined yet."
        ),
    }

    recommendations = _recommendations(context, sufficient, n, prop_count, entities)
    limitations = [DIRECTIONAL_CAVEAT]
    if not sufficient:
        limitations.append(
            f"Sample is below the {MIN_QUERIES_FOR_VISIBILITY}-query minimum; "
            "treat the counts as anecdotal."
        )
    if total == 0:
        limitations.append(
            "Neither the property nor any tracked competitor was mentioned in the "
            "sampled responses."
        )

    return {
        **base,
        "has_competitors": True,
        "has_ai_data": True,
        "date_range": {
            "start": min(r.executed_at.date() for r in records).isoformat(),
            "end": max(r.executed_at.date() for r in records).isoformat(),
        },
        "sample": {
            "total_queries": n,
            "sufficient": sufficient,
            "minimum": MIN_QUERIES_FOR_VISIBILITY,
        },
        "share_of_voice": share_of_voice,
        "recommendations": recommendations,
        "limitations": limitations,
    }


def _recommendations(context, sufficient, n, prop_count, entities) -> list[dict]:
    if not sufficient:
        return [
            {
                "title": "Run more AI Visibility queries",
                "reason": f"Only {n} of the recommended {MIN_QUERIES_FOR_VISIBILITY} "
                "queries have been run. Share of voice needs more before it means "
                "anything.",
                "state": "Insufficient data",
                "gate_reason": None,
            }
        ]
    recs = []

    def add(title, reason, base_state):
        block_state, block_reason = _gate(context, f"{title} {reason}")
        recs.append(
            {
                "title": title,
                "reason": reason,
                "state": block_state or base_state,
                "gate_reason": block_reason,
            }
        )

    ahead = [
        e for e in entities
        if not e["is_property"] and e["mentions"] > prop_count
    ]
    if ahead:
        names = ", ".join(e["name"] for e in ahead[:3])
        add(
            "Close the AI-answer gap with higher-mentioned competitors",
            f"{names} appeared in more sampled AI responses than this property "
            f"({prop_count}). Strengthen the site content and topics those "
            "queries target so the property surfaces more often.",
            "Actionable",
        )
    elif prop_count == 0:
        add(
            "Get the property mentioned in AI answers",
            "The property was not mentioned in any sampled AI response, while "
            "competitors were. Improve how the property surfaces for these prompts.",
            "Actionable",
        )
    return recs
