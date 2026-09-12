"""Daily rollups (Phase 19, slice 3). Dashboards read these, never raw
observations. Incremental: observations not yet rolled up mark their
(property, day) keys dirty; each dirty key is recomputed from ALL of that
key's observations and written delete-then-insert (per platform and "all"),
so a partial day or a re-derivation never double counts. A watermark in
app_state records the highest observation id folded in."""

from datetime import date, datetime, timedelta, timezone

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import (
    AICitation,
    AIClusterVisibilityDaily,
    AIMarketDaily,
    AIPropertyObservation,
    AIRun,
    AIVisibilityDaily,
    AIVisibilityQuery,
    AppState,
)
from app.models.ai_observations import METRIC_VERSION, PLATFORM_ALL
from app.services.observatory.tenancy import property_org_id

WATERMARK_KEY = "rollup_watermark_observation_id"


def _day(dt: datetime) -> date:
    return dt.date()


def _day_start(day: date) -> datetime:
    return datetime.combine(day, datetime.min.time())


def _key(*parts) -> str:
    return ":".join("" if p is None else str(p) for p in parts)


def _empty_counts() -> dict:
    return {
        "eligible_count": 0, "mentioned_count": 0, "cited_count": 0, "recommended_count": 0,
        "owned_citation_count": 0, "tracked_citation_count": 0, "total_citation_count": 0,
        "property_mention_responses": 0, "competitor_mention_count": 0, "competitor_win_count": 0,
        "sentiment_pos": 0, "sentiment_neu": 0, "sentiment_neg": 0, "runs_count": 0,
    }


def _accumulate(counts: dict, o: AIPropertyObservation) -> None:
    counts["eligible_count"] += 1 if o.eligible else 0
    counts["runs_count"] += 1
    if not o.eligible:
        return
    counts["mentioned_count"] += 1 if o.mentioned else 0
    counts["property_mention_responses"] += 1 if o.mentioned else 0
    counts["cited_count"] += 1 if o.cited else 0
    counts["recommended_count"] += 1 if o.recommended else 0
    counts["owned_citation_count"] += o.citation_count or 0
    counts["tracked_citation_count"] += (o.citation_count or 0) + (o.competitor_cited_count or 0)
    counts["total_citation_count"] += o.total_citation_count or 0
    counts["competitor_mention_count"] += o.competitor_mentioned_count or 0
    counts["competitor_win_count"] += 1 if (o.competitor_mentioned_count and not o.mentioned) else 0
    if o.mentioned:
        if o.sentiment == "positive":
            counts["sentiment_pos"] += 1
        elif o.sentiment == "negative":
            counts["sentiment_neg"] += 1
        else:
            counts["sentiment_neu"] += 1


def _dirty_keys(db: Session, property_ids: list[int] | None, full: bool) -> set[tuple[int, date]]:
    q = db.query(AIPropertyObservation.property_id, AIPropertyObservation.observed_at)
    if property_ids:
        q = q.filter(AIPropertyObservation.property_id.in_(property_ids))
    if not full:
        q = q.filter(AIPropertyObservation.rolled_up.is_(False))
    return {(pid, _day(ts)) for pid, ts in q.all()}


def update_property_rollups(
    db: Session, property_ids: list[int] | None = None, full: bool = False
) -> dict:
    keys = _dirty_keys(db, property_ids, full)
    written = 0
    for pid, day in sorted(keys):
        obs = (
            db.query(AIPropertyObservation)
            .filter(
                AIPropertyObservation.property_id == pid,
                AIPropertyObservation.observed_at >= _day_start(day),
                AIPropertyObservation.observed_at < _day_start(day + timedelta(days=1)),
            )
            .all()
        )
        org_id = property_org_id(db, pid)
        by_platform: dict[str, dict] = {PLATFORM_ALL: _empty_counts()}
        for o in obs:
            _accumulate(by_platform[PLATFORM_ALL], o)
            _accumulate(by_platform.setdefault(o.platform, _empty_counts()), o)
        db.query(AIVisibilityDaily).filter(
            AIVisibilityDaily.property_id == pid, AIVisibilityDaily.day == day
        ).delete(synchronize_session="fetch")
        for platform, counts in by_platform.items():
            db.add(AIVisibilityDaily(
                day=day, organization_id=org_id, property_id=pid, platform=platform,
                metric_version=METRIC_VERSION, rollup_key=_key(pid, platform, day.isoformat()), **counts,
            ))
            written += 1
        _update_cluster_rollups_for(db, pid, day, obs)
        for o in obs:
            o.rolled_up = True
    max_id = db.query(func.max(AIPropertyObservation.id)).scalar() or 0
    state = db.get(AppState, WATERMARK_KEY)
    value = {"observation_id": max_id, "updated_at": datetime.now(timezone.utc).isoformat()}
    if state is None:
        db.add(AppState(key=WATERMARK_KEY, value=value))
    else:
        state.value = value
    db.commit()
    return {"keys": len(keys), "rows_written": written, "watermark_observation_id": max_id}


def _update_cluster_rollups_for(db: Session, pid: int, day: date, obs: list[AIPropertyObservation]) -> None:
    db.query(AIClusterVisibilityDaily).filter(
        AIClusterVisibilityDaily.property_id == pid, AIClusterVisibilityDaily.day == day
    ).delete(synchronize_session="fetch")
    by_cluster: dict[int, dict] = {}
    for o in obs:
        if o.cluster_id is None or not o.eligible:
            continue
        c = by_cluster.setdefault(o.cluster_id, {
            "eligible_count": 0, "mentioned_count": 0, "cited_count": 0, "recommended_count": 0,
            "competitor_mention_count": 0, "competitor_win_count": 0,
        })
        c["eligible_count"] += 1
        c["mentioned_count"] += 1 if o.mentioned else 0
        c["cited_count"] += 1 if o.cited else 0
        c["recommended_count"] += 1 if o.recommended else 0
        c["competitor_mention_count"] += o.competitor_mentioned_count or 0
        c["competitor_win_count"] += 1 if (o.competitor_mentioned_count and not o.mentioned) else 0
    for cluster_id, counts in by_cluster.items():
        db.add(AIClusterVisibilityDaily(
            day=day, property_id=pid, cluster_id=cluster_id, metric_version=METRIC_VERSION,
            rollup_key=_key(pid, cluster_id, day.isoformat()), **counts,
        ))


def update_market_rollups(db: Session, market_ids: list[int] | None = None, days: int = 90) -> dict:
    """Per (market, platform, day): runs, responses, properties scored,
    citations, distinct domains. Recomputed for the trailing window."""
    since = _day_start(datetime.now(timezone.utc).date() - timedelta(days=days))
    runs_q = db.query(AIRun).filter(AIRun.market_id.isnot(None), AIRun.started_at >= since)
    if market_ids:
        runs_q = runs_q.filter(AIRun.market_id.in_(market_ids))
    runs = runs_q.all()
    keys: dict[tuple[int, str, date], dict] = {}
    for r in runs:
        k = (r.market_id, r.platform, _day(r.started_at))
        c = keys.setdefault(k, {"runs_count": 0, "responses_count": 0, "properties_scored": 0,
                                "citations_count": 0, "domains": set()})
        c["runs_count"] += 1
        if r.status == "success":
            resp = db.query(AIVisibilityQuery).filter_by(run_id=r.id).first()
            if resp is not None:
                c["responses_count"] += 1
                c["properties_scored"] += db.query(func.count(AIPropertyObservation.id)).filter_by(
                    response_id=resp.id).scalar() or 0
                for (dom,) in db.query(AICitation.domain).filter_by(response_id=resp.id).all():
                    c["citations_count"] += 1
                    c["domains"].add(dom)
    touched = {(m, p, d) for (m, p, d) in keys}
    for (market_id, platform, day), c in keys.items():
        db.query(AIMarketDaily).filter_by(market_id=market_id, platform=platform, day=day).delete(
            synchronize_session="fetch")
        db.add(AIMarketDaily(
            day=day, market_id=market_id, platform=platform, runs_count=c["runs_count"],
            responses_count=c["responses_count"], properties_scored=c["properties_scored"],
            citations_count=c["citations_count"], distinct_domains=len(c["domains"]),
            metric_version=METRIC_VERSION, rollup_key=_key(market_id, platform, day.isoformat()),
        ))
    db.commit()
    return {"keys": len(touched)}


def rebuild_rollups(db: Session, property_ids: list[int] | None = None) -> dict:
    out = update_property_rollups(db, property_ids=property_ids, full=True)
    out["market"] = update_market_rollups(db)
    return out
