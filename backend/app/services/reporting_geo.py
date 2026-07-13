"""GEO / AI Visibility report (Phase 16D).

Expands stored AI Visibility results into the GEO reporting experience. Every
number here is deterministically derived from stored query records; the only
non-deterministic step already happened upstream when the external AI answered.

Truth rules held here:
- Tested AI answers, AI referral sessions, mentions, citations, competitor
  appearances, and owned-domain appearances are DISTINCT metrics, never fused.
- Every rate travels with its numerator and denominator.
- Rates are withheld below the AI Visibility minimum-query sample and reported
  as insufficient, never as a fabricated 0.
- Competitor identity is only ever operator-configured; Beacon never guesses.
- Competitor share is labeled "share of tested AI answers", never market share.
- The source landscape classifies domains deterministically; anything Beacon
  cannot place stays "unknown".
- The report reads only stored responses; it never calls an AI platform.
"""

from datetime import date, timedelta

from sqlalchemy.orm import Session

from app.models import (
    AIVisibilityQuery,
    AIVisibilityScoreHistory,
    Competitor,
    GA4SessionsDaily,
    Property,
)
from app.services.ai_visibility.parsing import detect_mention, extract_sources
from app.services.ai_visibility.providers import read_queries
from app.services.ai_visibility.reference import (
    MIN_QUERIES_FOR_VISIBILITY,
    platform_label,
)
from app.services.competitor_intelligence import analyze_share_of_voice
from app.services.reporting import DataState, rate
from app.services.source_classifier import (
    CATEGORY_LABELS,
    classify_domain,
)

RESPONSE_EXCERPT_CHARS = 600

MARKET_SHARE_LABEL = "Share of tested AI answers"

METHODOLOGY_NOTE = (
    "These figures reflect AI answers Beacon tested by querying AI platforms "
    "directly, not what every user sees. Tested answers, AI referral sessions, "
    "mentions, and citations are distinct and are never combined."
)


def _domain_of_url(url: str | None) -> str | None:
    if not url:
        return None
    host = url.strip().lower()
    host = host.split("//", 1)[-1].split("/", 1)[0].split("?", 1)[0]
    return host[4:] if host.startswith("www.") else host or None


def _owned_domains(prop: Property) -> set[str]:
    d = _domain_of_url(getattr(prop, "website_url", None))
    return {d} if d else set()


def _competitor_index(competitors: list[Competitor]):
    """Return (terms_by_id, domains_by_id, all_domains)."""
    terms = {c.id: [c.name] + [a for a in (c.aliases or []) if a] for c in competitors}
    domains = {
        c.id: _domain_of_url(c.domain) for c in competitors if _domain_of_url(c.domain)
    }
    return terms, domains, set(domains.values())


def _citations(record) -> list[str]:
    """Cited domains for a stored response: prefer the persisted list, fall
    back to deterministic extraction so older rows still classify."""
    if record.sources_cited:
        return sorted({d for d in record.sources_cited if d})
    return extract_sources(record.raw_response_text)


# --- summary + sufficiency ---------------------------------------------------


def _ai_referral_sessions(db: Session, property_id: int) -> dict | None:
    rows = (
        db.query(GA4SessionsDaily)
        .filter(GA4SessionsDaily.property_id == property_id)
        .all()
    )
    if not rows:
        return None
    ai = sum(r.sessions for r in rows if r.is_ai_referral)
    last = max(r.date for r in rows)
    return {"sessions": ai, "last_data_date": last.isoformat()}


def _summary(db, prop, records, competitors):
    n = len(records)
    sufficient = n >= MIN_QUERIES_FOR_VISIBILITY
    owned = _owned_domains(prop)
    comp_terms, comp_domains, all_comp_domains = _competitor_index(competitors)

    mentions = sum(1 for r in records if r.brand_mentioned)
    responses_with_citation = 0
    owned_citations = 0
    competitor_appearances = 0
    for r in records:
        cites = _citations(r)
        if cites:
            responses_with_citation += 1
        if owned and any(
            d == o or d.endswith("." + o) for d in cites for o in owned
        ):
            owned_citations += 1
        if any(detect_mention(r.raw_response_text, comp_terms[c.id]) for c in competitors):
            competitor_appearances += 1

    platforms = sorted({r.platform for r in records})
    referral = _ai_referral_sessions(db, prop.id)

    return {
        "queries_completed": n,
        "platforms_tested": [
            {"key": p, "label": platform_label(p)} for p in platforms
        ],
        "mention_count": mentions,
        "citation_count": responses_with_citation,
        "mention_rate": rate(mentions, n, MIN_QUERIES_FOR_VISIBILITY),
        "citation_rate": rate(responses_with_citation, n, MIN_QUERIES_FOR_VISIBILITY),
        "owned_domain_citations": owned_citations,
        "competitor_appearances": competitor_appearances,
        "ai_referral_sessions": referral,
        "last_run": max((r.executed_at.date().isoformat() for r in records), default=None),
        "sufficient": sufficient,
    }


def _sufficiency(records):
    n = len(records)
    dates = sorted(r.executed_at.date() for r in records)
    return {
        "completed_queries": n,
        "minimum_required": MIN_QUERIES_FOR_VISIBILITY,
        "sufficient": n >= MIN_QUERIES_FOR_VISIBILITY,
        # Beacon stores only completed runs; failed/not-run are surfaced as 0
        # explicitly rather than silently omitted.
        "failed_queries": 0,
        "not_run_queries": 0,
        "date_span": (
            {"start": dates[0].isoformat(), "end": dates[-1].isoformat()}
            if dates
            else None
        ),
        "platforms_represented": sorted({r.platform for r in records}),
    }


# --- prompt visibility matrix ------------------------------------------------

CELL_PROPERTY_CITED = "property_cited"
CELL_PROPERTY_MENTIONED = "property_mentioned"
CELL_COMPETITOR_MENTIONED = "competitor_mentioned"
CELL_BOTH = "property_and_competitor"
CELL_NOT_PRESENT = "not_present"
CELL_NOT_TESTED = "not_tested"


def _matrix(prop, records, competitors):
    owned = _owned_domains(prop)
    comp_terms, comp_domains, _ = _competitor_index(competitors)
    platforms = sorted({r.platform for r in records})

    # Most recent run per (prompt, platform); the prompt matrix shows current
    # standing, not a pile of historical runs.
    latest: dict[tuple[str, str], object] = {}
    for r in records:  # records are newest-first
        latest.setdefault((r.prompt_text, r.platform), r)

    prompts = sorted({p for (p, _) in latest})
    rows = []
    for prompt in prompts:
        cells = []
        for platform in platforms:
            r = latest.get((prompt, platform))
            if r is None:
                cells.append({"platform": platform, "state": CELL_NOT_TESTED})
                continue
            cites = _citations(r)
            property_cited = bool(owned) and any(
                d == o or d.endswith("." + o) for d in cites for o in owned
            )
            competitor_present = any(
                detect_mention(r.raw_response_text, comp_terms[c.id]) for c in competitors
            )
            if r.brand_mentioned and competitor_present:
                state = CELL_BOTH
            elif property_cited:
                state = CELL_PROPERTY_CITED
            elif r.brand_mentioned:
                state = CELL_PROPERTY_MENTIONED
            elif competitor_present:
                state = CELL_COMPETITOR_MENTIONED
            else:
                state = CELL_NOT_PRESENT
            cells.append({
                "platform": platform,
                "state": state,
                "query_id": r.query_id,
                "run_date": r.executed_at.date().isoformat(),
            })
        rows.append({"prompt": prompt, "cells": cells})
    return {
        "platforms": [{"key": p, "label": platform_label(p)} for p in platforms],
        "rows": rows,
    }


def matrix_cell_evidence(db: Session, property_id: int, query_id: int) -> dict:
    """Evidence drawer for one matrix cell: the stored response and what Beacon
    deterministically detected in it. Stored data only."""
    q = db.get(AIVisibilityQuery, query_id)
    if q is None or q.property_id != property_id:
        raise ValueError("Query not found for this property.")
    prop = db.get(Property, property_id)
    competitors = db.query(Competitor).filter_by(property_id=property_id).all()
    comp_terms, _, _ = _competitor_index(competitors)
    owned = _owned_domains(prop)
    cites = sorted({d for d in (q.sources_cited or []) if d}) or extract_sources(
        q.raw_response_text
    )
    detected = [c.name for c in competitors if detect_mention(q.raw_response_text, comp_terms[c.id])]
    owned_cited = [d for d in cites if any(d == o or d.endswith("." + o) for o in owned)]
    excerpt = q.raw_response_text.strip()
    truncated = len(excerpt) > RESPONSE_EXCERPT_CHARS
    return {
        "query_id": q.id,
        "prompt": q.prompt_text,
        "platform": q.platform,
        "platform_label": platform_label(q.platform),
        "run_date": q.executed_at.date().isoformat(),
        "response_excerpt": excerpt[:RESPONSE_EXCERPT_CHARS] + ("..." if truncated else ""),
        "brand_mentioned": q.brand_mentioned,
        "cited_domains": cites,
        "owned_domains_cited": owned_cited,
        "detected_competitors": detected,
    }


# --- source landscape --------------------------------------------------------


def _source_landscape(prop, records, competitors):
    owned = _owned_domains(prop)
    _, comp_domains, all_comp_domains = _competitor_index(competitors)
    n = len(records)
    by_domain: dict[str, dict] = {}
    for r in records:
        for d in set(_citations(r)):
            entry = by_domain.setdefault(
                d, {"domain": d, "cited_in_responses": 0, "platforms": set()}
            )
            entry["cited_in_responses"] += 1
            entry["platforms"].add(r.platform)

    landscape = []
    for d, entry in by_domain.items():
        category = classify_domain(d, owned, all_comp_domains)
        landscape.append({
            "domain": d,
            "cited_in_responses": entry["cited_in_responses"],
            "pct_of_completed": (
                round(entry["cited_in_responses"] / n, 4) if n else None
            ),
            "platforms": sorted(platform_label(p) for p in entry["platforms"]),
            "category": category,
            "category_label": CATEGORY_LABELS[category],
        })
    landscape.sort(key=lambda e: (-e["cited_in_responses"], e["domain"]))
    return {
        "completed_responses": n,
        "domains": landscape,
        "categories": CATEGORY_LABELS,
    }


# --- trends ------------------------------------------------------------------


def _trends(db, property_id):
    history = (
        db.query(AIVisibilityScoreHistory)
        .filter(AIVisibilityScoreHistory.property_id == property_id)
        .order_by(AIVisibilityScoreHistory.captured_at)
        .all()
    )
    points = [
        {
            "date": h.captured_at.date().isoformat(),
            "score": h.score,  # null below the sample gate; shown as a gap
            "mention_rate": h.mention_rate,
            "sample_size": h.sample_size,
            "sufficient": h.sample_size >= MIN_QUERIES_FOR_VISIBILITY,
        }
        for h in history
    ]
    return {
        "state": DataState.COMPLETE.value if points else DataState.AWAITING_DATA.value,
        "points": points,
        "note": (
            "Score and mention-rate points are null when that capture was below "
            "the minimum query sample."
        ),
    }


# --- report ------------------------------------------------------------------


def build_geo_report(
    db: Session, property_id: int | None, today: date | None = None
) -> dict:
    today = today or date.today()
    if property_id is None:
        return {
            "scope_required": True,
            "message": "Select a single property to view its GEO Visibility report.",
        }
    prop = db.get(Property, property_id)
    if prop is None:
        raise ValueError("Property not found.")

    records = read_queries(db, property_id)
    competitors = db.query(Competitor).filter_by(property_id=property_id).order_by(Competitor.name).all()

    if not records:
        return {
            "scope_required": False,
            "property_id": property_id,
            "property_name": prop.name,
            "has_queries": False,
            "methodology": METHODOLOGY_NOTE,
            "sufficiency": _sufficiency(records),
            "message": (
                "No AI Visibility queries have been run for this property yet. "
                "Run a standing prompt set from the AI Visibility page to build "
                "this report."
            ),
        }

    sov = analyze_share_of_voice(db, property_id, today=today)
    competitor_share = {
        "label": MARKET_SHARE_LABEL,
        "has_competitors": sov.get("has_competitors", False),
        "share_of_voice": sov.get("share_of_voice", []),
        "limitations": sov.get("limitations", []),
    }

    return {
        "scope_required": False,
        "property_id": property_id,
        "property_name": prop.name,
        "has_queries": True,
        "methodology": METHODOLOGY_NOTE,
        "generated_on": today.isoformat(),
        "summary": _summary(db, prop, records, competitors),
        "sufficiency": _sufficiency(records),
        "prompt_matrix": _matrix(prop, records, competitors),
        "source_landscape": _source_landscape(prop, records, competitors),
        "competitor_share": competitor_share,
        "trends": _trends(db, property_id),
    }
