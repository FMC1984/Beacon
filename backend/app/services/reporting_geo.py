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

from datetime import date, datetime, timedelta

from sqlalchemy.orm import Session

from app.models import (
    AIPropertyObservation,
    AIVisibilityQuery,
    AIVisibilityScoreHistory,
    Competitor,
    GA4SessionsDaily,
    Property,
)
from app.services.ai_visibility.parsing import detect_mention, extract_sources
from app.connectors.base import AIVisibilityRecord
from app.services.ai_visibility.reference import (
    MIN_QUERIES_FOR_VISIBILITY,
    platform_label,
)
from app.services.competitor_intelligence import analyze_share_of_voice
from app.services.observatory import utc_today
from app.services.observatory.metrics import metric_from_counts
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
    "mentions, and citations are distinct and are never combined. Mention rate "
    "and citation rate are the AI Visibility Observatory's AI Visibility and "
    "Citation Rate, computed over the same monitored answers, so the number "
    "here is the number on the AI Visibility tab."
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


def _observations(db: Session, property_id: int, since: datetime | None, until: datetime) -> list[AIPropertyObservation]:
    q = db.query(AIPropertyObservation).filter(
        AIPropertyObservation.property_id == property_id, AIPropertyObservation.eligible.is_(True),
        AIPropertyObservation.observed_at < until,
    )
    if since is not None:
        q = q.filter(AIPropertyObservation.observed_at >= since)
    return q.order_by(AIPropertyObservation.observed_at).all()


def _records(db: Session, property_id: int, observations) -> list[AIVisibilityRecord]:
    """Stored responses behind the observations, newest first, with
    brand_mentioned taken from the per-property observation so a shared
    market answer reads the same here as on the AI Visibility tab."""
    if not observations:
        return []
    by_response = {o.response_id: o for o in observations}
    rows = (
        db.query(AIVisibilityQuery)
        .filter(AIVisibilityQuery.id.in_(list(by_response)))
        .order_by(AIVisibilityQuery.executed_at.desc(), AIVisibilityQuery.id.desc())
        .all()
    )
    return [
        AIVisibilityRecord(
            property_id=property_id, query_id=r.id, platform=r.platform, prompt_text=r.prompt_text,
            raw_response_text=r.raw_response_text, executed_at=r.executed_at,
            brand_mentioned=bool(by_response[r.id].mentioned), sources_cited=r.sources_cited or [],
        )
        for r in rows
    ]


def _summary(db, prop, observations):
    """Headline figures from the Observatory's derived observations, with the
    Observatory's own keys and sample gate: mention rate is AI Visibility
    (mentioned / eligible), citation rate is Citation Rate (owned-site
    citations / eligible). Responses citing anything at all is kept as a
    separate count, never as the rate."""
    n = len(observations)
    mentions = sum(1 for o in observations if o.mentioned)
    owned_citations = sum(1 for o in observations if o.cited)
    any_citation = sum(1 for o in observations if (o.total_citation_count or 0) > 0)
    competitor_appearances = sum(1 for o in observations if (o.competitor_mentioned_count or 0) > 0)
    platforms = sorted({o.platform for o in observations})
    referral = _ai_referral_sessions(db, prop.id)
    return {
        "queries_completed": n,
        "platforms_tested": [{"key": p, "label": platform_label(p)} for p in platforms],
        "mention_count": mentions,
        "citation_count": any_citation,
        "mention_rate": metric_from_counts("ai_visibility", mentions, n),
        "citation_rate": metric_from_counts("citation_rate", owned_citations, n),
        "owned_domain_citations": owned_citations,
        "competitor_appearances": competitor_appearances,
        "ai_referral_sessions": referral,
        "last_run": max((o.observed_at.date().isoformat() for o in observations), default=None),
        "sufficient": n >= MIN_QUERIES_FOR_VISIBILITY,
        "definition": "observatory",
    }


def _sufficiency(observations):
    n = len(observations)
    dates = sorted(o.observed_at.date() for o in observations)
    return {
        "completed_queries": n,
        "minimum_required": MIN_QUERIES_FOR_VISIBILITY,
        "sufficient": n >= MIN_QUERIES_FOR_VISIBILITY,
        # Only scored answers are counted; failed and never-run attempts live
        # in the ai_runs ledger and are surfaced as 0 here explicitly.
        "failed_queries": 0,
        "not_run_queries": 0,
        "date_span": (
            {"start": dates[0].isoformat(), "end": dates[-1].isoformat()}
            if dates
            else None
        ),
        "platforms_represented": sorted({o.platform for o in observations}),
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
    obs = (
        db.query(AIPropertyObservation).filter_by(property_id=property_id, response_id=query_id).one_or_none()
        if q is not None else None
    )
    if q is None or (q.property_id != property_id and obs is None):
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

    # Question-set success criteria: deterministic containment check of the
    # prompt's must_contain components against the stored response.
    from app.models import AIVisibilityPrompt
    from app.services.ai_visibility.question_set import evaluate_must_contain

    prompt_row = (
        db.query(AIVisibilityPrompt)
        .filter(
            AIVisibilityPrompt.property_id == property_id,
            AIVisibilityPrompt.prompt_text == q.prompt_text,
        )
        .first()
    )
    required = evaluate_must_contain(
        q.raw_response_text, prompt_row.must_contain if prompt_row else None
    )
    return {
        "query_id": q.id,
        "prompt": q.prompt_text,
        "platform": q.platform,
        "platform_label": platform_label(q.platform),
        "run_date": q.executed_at.date().isoformat(),
        "response_excerpt": excerpt[:RESPONSE_EXCERPT_CHARS] + ("..." if truncated else ""),
        "brand_mentioned": bool(obs.mentioned) if obs is not None else q.brand_mentioned,
        "cited_domains": cites,
        "owned_domains_cited": owned_cited,
        "detected_competitors": detected,
        # Empty when the prompt has no must_contain criteria.
        "required_components": required,
        "owning_url": prompt_row.owning_url if prompt_row else None,
        "volatile": bool(prompt_row.volatile) if prompt_row else False,
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


def _trends(observations):
    """Daily AI Visibility over the same observations: mentioned / eligible
    per day, null below the sample gate. The same series the Trends tab
    draws, without depending on the rollup job having run."""
    by_day: dict[date, list] = {}
    for o in observations:
        by_day.setdefault(o.observed_at.date(), []).append(o)
    points = []
    for day in sorted(by_day):
        rows = by_day[day]
        r = rate(sum(1 for o in rows if o.mentioned), len(rows), MIN_QUERIES_FOR_VISIBILITY)
        points.append({
            "date": day.isoformat(),
            "mention_rate": r["value"],
            "sample_size": len(rows),
            "sufficient": r["value"] is not None,
        })
    return {
        "state": DataState.COMPLETE.value if points else DataState.AWAITING_DATA.value,
        "points": points,
        "note": "Days below the minimum answer sample show no rate rather than a misleading point.",
    }


# --- report ------------------------------------------------------------------


def build_geo_report(
    db: Session, property_id: int | None, today: date | None = None, days: int | None = None
) -> dict:
    """`days` limits every section to a trailing window ending today; None
    means all history (what the report showed before it had a window)."""
    # UTC, like the Observatory, so the report's window ends on the same day
    # as the AI Visibility tab's and the two never disagree by one day's runs.
    today = today or utc_today()
    since = datetime.combine(today - timedelta(days=days - 1), datetime.min.time()) if days else None
    until = datetime.combine(today + timedelta(days=1), datetime.min.time())
    if property_id is None:
        return {
            "scope_required": True,
            "message": "Select a single property to view its GEO Visibility report.",
        }
    prop = db.get(Property, property_id)
    if prop is None:
        raise ValueError("Property not found.")

    observations = _observations(db, property_id, since, until)
    records = _records(db, property_id, observations)
    competitors = db.query(Competitor).filter_by(property_id=property_id).order_by(Competitor.name).all()

    if not records:
        return {
            "scope_required": False,
            "property_id": property_id,
            "property_name": prop.name,
            "has_queries": False,
            "methodology": METHODOLOGY_NOTE,
            "sufficiency": _sufficiency(observations),
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
        "window_days": days,
        "summary": _summary(db, prop, observations),
        "sufficiency": _sufficiency(observations),
        "prompt_matrix": _matrix(prop, records, competitors),
        "source_landscape": _source_landscape(prop, records, competitors),
        "competitor_share": competitor_share,
        "trends": _trends(observations),
    }
