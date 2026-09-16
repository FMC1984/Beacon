"""Build the Observatory scale rollups (Phase 19).

Each builder calls the SAME function the live readers call and stores the
result, so the cache cannot drift into its own arithmetic: if
`source_influence` changes tomorrow, the rollup changes with it. Reads go
through `*_cached` helpers that return the stored rows when a matching
rollup exists and fall back to computing live when it does not, so nothing
ever waits on a job having run.
"""

from datetime import date, timedelta

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import (
    AICompetitorStat,
    AIPropertyObservation,
    AIRun,
    AIRunCostDaily,
    AISourceDomainRollup,
    Competitor,
    Mention,
    Property,
)
from app.models.ai_rollups import PERIOD_WINDOW, ROLLUP_VERSION
from app.models.mention import ENTITY_COMPETITOR
from app.services.ai_visibility.reference import MIN_QUERIES_FOR_VISIBILITY
from app.services.observatory import utc_today
from app.services.observatory.costs import cost_report
from app.services.observatory.metrics import source_influence
from app.services.observatory.observability import log_event
from app.services.observatory.tenancy import org_property_ids, property_org_id

# Windows worth caching. A request for any other window computes live.
CACHED_WINDOWS = (7, 30, 90)


def window_label(days: int) -> str:
    return f"{days}d"


def _bounds(days: int, today: date) -> tuple[date, date]:
    return today - timedelta(days=days - 1), today


def _key(*parts) -> str:
    return ":".join("" if p is None else str(p) for p in parts)


# --- source domains ----------------------------------------------------------


def rebuild_source_domains(db: Session, property_id: int, days: int, today: date | None = None) -> int:
    """Store the live source-influence result for one property and window."""
    today = today or utc_today()
    start, end = _bounds(days, today)
    period = window_label(days)
    live = source_influence(db, property_id, start, end, limit=1000)
    org_id = property_org_id(db, property_id)
    prop = db.get(Property, property_id)

    db.query(AISourceDomainRollup).filter_by(property_id=property_id, period=period).delete(
        synchronize_session=False
    )
    for row in live["domains"]:
        db.add(AISourceDomainRollup(
            organization_id=org_id, property_id=property_id,
            market_id=prop.market_id if prop else None, period=period, period_kind=PERIOD_WINDOW,
            window_start=start, window_end=end, domain=row["domain"], source_type=row["source_type"],
            citations=row["citations"], responses=row["responses"], share=row["share"],
            rollup_version=ROLLUP_VERSION,
            rollup_key=_key(property_id, period, row["domain"], row["source_type"]),
        ))
    db.commit()
    return len(live["domains"])


def source_influence_cached(
    db: Session, property_id: int, days: int, today: date | None = None, limit: int = 25
) -> dict:
    """Stored rollup when one exists for this exact window, else live."""
    today = today or utc_today()
    start, end = _bounds(days, today)
    rows = (
        db.query(AISourceDomainRollup)
        .filter_by(property_id=property_id, period=window_label(days), window_end=end,
                   rollup_version=ROLLUP_VERSION)
        .order_by(AISourceDomainRollup.citations.desc(), AISourceDomainRollup.domain)
        .all()
    )
    if not rows:
        return {**source_influence(db, property_id, start, end, limit=limit), "from_rollup": False}
    from app.services.observatory.metrics import METRIC_DEFINITIONS
    from app.services.observatory import LABEL_MEASURED

    return {
        "total_citations": sum(r.citations for r in rows),
        "domains": [
            {"domain": r.domain, "source_type": r.source_type, "citations": r.citations,
             "responses": r.responses, "share": r.share}
            for r in rows[:limit]
        ],
        "data_label": LABEL_MEASURED,
        "formula": METRIC_DEFINITIONS["source_influence"]["formula"],
        "from_rollup": True,
    }


# --- run costs ---------------------------------------------------------------


def rebuild_run_costs(db: Session, organization_id: int | None = None, days: int = 90,
                      today: date | None = None) -> int:
    """One row per (day, provider, model, scope) for the trailing window.
    Built straight off ai_runs, which is what cost_report reads."""
    today = today or utc_today()
    start = today - timedelta(days=days - 1)
    q = db.query(AIRun).filter(AIRun.started_at >= _dt(start))
    if organization_id is not None:
        q = q.filter(AIRun.organization_id == organization_id)
    runs = q.all()

    buckets: dict[tuple, list[AIRun]] = {}
    for r in runs:
        buckets.setdefault(
            (r.started_at.date(), r.organization_id, r.provider,
             r.model or r.model_requested, r.run_scope), []
        ).append(r)

    written = 0
    for (day, org_id, provider, model, scope), group in buckets.items():
        key = _key(org_id, day.isoformat(), provider, model, scope)
        db.query(AIRunCostDaily).filter_by(rollup_key=key).delete(synchronize_session=False)
        priced = [r for r in group if r.estimated_cost is not None]
        success_ids = [r.id for r in group if r.status == "success"]
        observations = (
            db.query(func.count(AIPropertyObservation.id))
            .filter(AIPropertyObservation.run_id.in_(success_ids)).scalar() or 0
        ) if success_ids else 0
        db.add(AIRunCostDaily(
            day=day, organization_id=org_id, provider=provider, model=model, run_scope=scope,
            runs=len(group),
            runs_success=sum(1 for r in group if r.status == "success"),
            runs_failed=sum(1 for r in group if r.status == "failed"),
            runs_discarded=sum(1 for r in group if r.status == "discarded"),
            priced_runs=len(priced),
            token_input=sum(r.token_input or 0 for r in group),
            token_output=sum(r.token_output or 0 for r in group),
            token_reasoning=sum(r.token_reasoning or 0 for r in group),
            token_cached=sum(r.token_cached or 0 for r in group),
            search_operations=sum(r.search_operations or 0 for r in group),
            estimated_usd=round(sum(r.estimated_cost for r in priced), 6) if priced else None,
            observations=observations, rollup_version=ROLLUP_VERSION, rollup_key=key,
        ))
        written += 1
    db.commit()
    return written


def _dt(day: date):
    from datetime import datetime

    return datetime.combine(day, datetime.min.time())


def cost_summary_cached(db: Session, organization_id: int, days: int = 30,
                        today: date | None = None) -> dict:
    """Totals for the window from the daily cost rollup. Falls back to the
    live report when the rollup has not been built for this window."""
    today = today or utc_today()
    start = today - timedelta(days=days - 1)
    rows = (
        db.query(AIRunCostDaily)
        .filter(AIRunCostDaily.organization_id == organization_id,
                AIRunCostDaily.day >= start, AIRunCostDaily.day <= today,
                AIRunCostDaily.rollup_version == ROLLUP_VERSION)
        .all()
    )
    if not rows:
        live = cost_report(db, days=days, today=today, organization_id=organization_id)
        return {**live["total"], "from_rollup": False}
    priced_runs = sum(r.priced_runs for r in rows)
    total_runs = sum(r.runs for r in rows)
    usd = sum(r.estimated_usd for r in rows if r.estimated_usd is not None) if priced_runs else None
    from app.services.observatory.costs import _cost_block
    from app.services.observatory import LABEL_OBSERVED

    by_status = {
        "success": sum(r.runs_success for r in rows),
        "failed": sum(r.runs_failed for r in rows),
        "discarded": sum(r.runs_discarded for r in rows),
    }
    return {
        "runs": total_runs,
        "by_status": {k: v for k, v in sorted(by_status.items()) if v},
        "tokens": {
            "label": LABEL_OBSERVED,
            "input": sum(r.token_input for r in rows),
            "output": sum(r.token_output for r in rows),
            "reasoning": sum(r.token_reasoning for r in rows),
            "cached": sum(r.token_cached for r in rows),
        },
        "search_operations": sum(r.search_operations for r in rows),
        "cost": _cost_block(priced_runs, total_runs, usd),
        "from_rollup": True,
    }


# --- competitor standing -----------------------------------------------------


def rebuild_competitor_stats(db: Session, property_id: int, days: int, today: date | None = None) -> int:
    """Per tracked competitor, over the property's eligible observations:
    who was named, who was cited, who won the answers the other missed."""
    today = today or utc_today()
    start, end = _bounds(days, today)
    period = window_label(days)
    competitors = db.query(Competitor).filter_by(property_id=property_id).order_by(Competitor.id).all()
    db.query(AICompetitorStat).filter_by(property_id=property_id, period=period).delete(
        synchronize_session=False
    )
    if not competitors:
        db.commit()
        return 0

    observations = (
        db.query(AIPropertyObservation)
        .filter(AIPropertyObservation.property_id == property_id,
                AIPropertyObservation.eligible.is_(True),
                AIPropertyObservation.observed_at >= _dt(start),
                AIPropertyObservation.observed_at < _dt(end + timedelta(days=1)))
        .all()
    )
    response_ids = [o.response_id for o in observations]
    mentioned_by_response = {o.response_id: o.mentioned for o in observations}
    property_cited = {o.response_id: bool(o.cited) for o in observations}
    property_citation_count = sum(o.citation_count or 0 for o in observations)

    comp_mentions: dict[int, set] = {c.id: set() for c in competitors}
    if response_ids:
        rows = db.query(Mention.entity_id, Mention.response_id).filter(
            Mention.response_id.in_(response_ids), Mention.entity_type == ENTITY_COMPETITOR,
            Mention.entity_id.in_([c.id for c in competitors]),
        ).all()
        for entity_id, response_id in rows:
            comp_mentions[entity_id].add(response_id)

    org_id = property_org_id(db, property_id)
    sample = len(observations)
    written = 0
    for c in competitors:
        named = comp_mentions[c.id]
        co = sum(1 for rid in named if mentioned_by_response.get(rid))
        comp_wins = sum(1 for rid in named if not mentioned_by_response.get(rid))
        prop_wins = sum(
            1 for rid, was in mentioned_by_response.items() if was and rid not in named
        )
        # Competitor citations are counted per response from the observation's
        # own tally, which is what the derived rows already measured.
        comp_citations = sum(
            (o.competitor_cited_count or 0) for o in observations if o.response_id in named
        )
        sufficient = sample >= MIN_QUERIES_FOR_VISIBILITY
        cite_total = property_citation_count + comp_citations
        key = _key(property_id, c.id, period)
        db.add(AICompetitorStat(
            organization_id=org_id, property_id=property_id, competitor_id=c.id,
            competitor_name=c.name, period=period, window_start=start, window_end=end,
            shared_responses=sample, competitor_mentions=len(named),
            property_mentions=sum(1 for v in mentioned_by_response.values() if v),
            co_mentions=co, competitor_wins=comp_wins, property_wins=prop_wins,
            competitor_citations=comp_citations,
            property_citations=property_citation_count,
            co_mention_rate=round(co / sample, 4) if sufficient and sample else None,
            competitor_win_rate=round(comp_wins / sample, 4) if sufficient and sample else None,
            citation_share=(
                round(property_citation_count / cite_total, 4) if sufficient and cite_total else None
            ),
            rollup_version=ROLLUP_VERSION, rollup_key=key,
        ))
        written += 1
    db.commit()
    return written


def competitor_stats(db: Session, property_id: int, days: int = 30, today: date | None = None) -> dict:
    """Stored standings; builds them on the spot if they are missing so a
    caller never sees an empty tab just because a job has not run."""
    today = today or utc_today()
    period = window_label(days)
    rows = db.query(AICompetitorStat).filter_by(
        property_id=property_id, period=period, window_end=today, rollup_version=ROLLUP_VERSION
    ).order_by(AICompetitorStat.competitor_mentions.desc(), AICompetitorStat.competitor_name).all()
    built = False
    if not rows and db.query(Competitor).filter_by(property_id=property_id).count():
        rebuild_competitor_stats(db, property_id, days, today)
        built = True
        rows = db.query(AICompetitorStat).filter_by(
            property_id=property_id, period=period, window_end=today
        ).order_by(AICompetitorStat.competitor_mentions.desc(), AICompetitorStat.competitor_name).all()
    return {
        "property_id": property_id,
        "window": {"start": (today - timedelta(days=days - 1)).isoformat(), "end": today.isoformat(),
                   "days": days},
        "minimum_sample": MIN_QUERIES_FOR_VISIBILITY,
        "from_rollup": not built,
        "competitors": [
            {"competitor_id": r.competitor_id, "name": r.competitor_name,
             "shared_responses": r.shared_responses, "competitor_mentions": r.competitor_mentions,
             "co_mentions": r.co_mentions, "competitor_wins": r.competitor_wins,
             "property_wins": r.property_wins, "competitor_citations": r.competitor_citations,
             "property_citations": r.property_citations, "co_mention_rate": r.co_mention_rate,
             "competitor_win_rate": r.competitor_win_rate, "citation_share": r.citation_share}
            for r in rows
        ],
        "note": ("Counts only competitors you track for this property. Rates are null below the "
                 f"{MIN_QUERIES_FOR_VISIBILITY}-response minimum rather than shown as zero."),
    }


# --- orchestration -----------------------------------------------------------


def prune_orphans(db: Session) -> int:
    """Drop cached rows for properties that no longer exist. A rebuild only
    refreshes properties it can see, so without this a deleted property's
    numbers would linger in the cache indefinitely."""
    live = db.query(Property.id).scalar_subquery()
    removed = 0
    for model in (AISourceDomainRollup, AICompetitorStat):
        removed += (
            db.query(model)
            .filter(model.property_id.isnot(None), model.property_id.notin_(live))
            .delete(synchronize_session=False)
        )
    if removed:
        db.commit()
    return removed


def rebuild_all(db: Session, organization_id: int | None = None, today: date | None = None) -> dict:
    """Refresh every scale rollup for an organization (or everything)."""
    today = today or utc_today()
    if organization_id is not None:
        property_ids = org_property_ids(db, organization_id)
    else:
        property_ids = [pid for (pid,) in db.query(Property.id).filter(Property.is_active.is_(True))]
    domains = competitors = 0
    for pid in property_ids:
        for days in CACHED_WINDOWS:
            domains += rebuild_source_domains(db, pid, days, today)
            competitors += rebuild_competitor_stats(db, pid, days, today)
    costs = rebuild_run_costs(db, organization_id=organization_id, today=today)
    pruned = prune_orphans(db)
    out = {"properties": len(property_ids), "source_domain_rows": domains, "pruned": pruned,
           "competitor_stat_rows": competitors, "cost_rows": costs,
           "windows": list(CACHED_WINDOWS)}
    log_event("scale_rollups.rebuilt", organization_id=organization_id, **out)
    return out
