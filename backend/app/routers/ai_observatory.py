"""AI Visibility Observatory API (Phase 19).

Slice 2 surface: the prompt library (generate, list, create, edit, cluster)
and markets. Slice 3: metrics meta, overview, trends, sources, citations,
derived observations, cluster opportunity score, market summary, shared
market runs, rollup rebuild. Later slices add competitors, recommendations,
accuracy, costs and schedule here.
"""

from datetime import date, datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import (
    AICitation,
    AIMarketDaily,
    AIPromptCluster,
    AIPropertyObservation,
    AIVisibilityPrompt,
    Market,
    Property,
)
from app.models.ai_observations import PLATFORM_ALL
from app.models.ai_prompt_library import PROMPT_SCOPES
from app.services.ai_visibility.reference import InvalidPlatformError, validate_platform
from app.services.observatory.assignments import assignments_for_property, subscribe_property
from app.services.observatory.clustering import cluster_prompts
from app.services.observatory.markets import market_members
from app.services.observatory.prompt_library import (
    PromptDraft,
    generate_market_prompts,
    generate_property_prompts,
    upsert_prompt,
)
from app.services.jobs.queue import enqueue
from app.services.observatory import LABEL_MEASURED, LABEL_MODELED, LABEL_OBSERVED, LABEL_UNAVAILABLE
from app.services.observatory.derivation import backfill_observations
from app.services.observatory.metrics import (
    METRIC_DEFINITIONS,
    metrics_for_window,
    prompt_coverage,
    source_influence,
    trend,
)
from app.services.observatory.opportunity_score import prompt_opportunity_score
from app.services.observatory.opportunity_score import weights as opportunity_weights
from app.services.observatory.rollups import rebuild_rollups
from app.services.observatory.taxonomy import topics
from app.services.reporting import compare_points, previous_window
from app.services.observatory.tenancy import property_org_id

router = APIRouter(prefix="/ai-observatory", tags=["ai-observatory"])


def _prompt_out(p: AIVisibilityPrompt) -> dict:
    return {
        "id": p.id,
        "prompt_text": p.prompt_text,
        "scope": p.scope,
        "platform": p.platform,
        "property_id": p.property_id,
        "market_id": p.market_id,
        "cluster_id": p.cluster_id,
        "topic_key": p.topic_key,
        "intent": p.intent,
        "importance": p.importance,
        "funnel_stage": p.funnel_stage,
        "active": p.active,
        "approved": p.approved,
        "is_representative": p.is_representative,
        "variant_group": p.variant_group,
        "repeat_count": p.repeat_count,
        "cadence": p.cadence,
        "generation_method": p.generation_method,
        "generated_from": p.generated_from,
        "last_run_at": p.last_run_at.isoformat() if p.last_run_at else None,
        "created_at": p.created_at.isoformat() if p.created_at else None,
    }


def _cluster_out(c: AIPromptCluster) -> dict:
    return {
        "id": c.id, "scope": c.scope, "label": c.label, "topic_key": c.topic_key, "intent": c.intent,
        "funnel_stage": c.funnel_stage, "importance": c.importance, "market_id": c.market_id,
        "property_id": c.property_id, "representative_prompt_id": c.representative_prompt_id,
        "variant_count": c.variant_count, "embedding_model": c.embedding_model,
    }


@router.get("/taxonomy")
def taxonomy():
    return {"topics": [{k: v for k, v in t.items() if k != "terms"} for t in topics()]}


@router.get("/markets")
def list_markets(db: Session = Depends(get_db)):
    rows = db.query(Market).order_by(Market.name).all()
    return {
        "markets": [
            {
                "id": m.id, "slug": m.slug, "name": m.name, "city": m.city, "state": m.state,
                "organization_id": m.organization_id, "is_active": m.is_active,
                "property_count": len(market_members(db, m.id)),
            }
            for m in rows
        ]
    }


@router.get("/markets/{market_id}")
def get_market(market_id: int, db: Session = Depends(get_db)):
    m = db.get(Market, market_id)
    if m is None:
        raise HTTPException(status_code=404, detail="Market not found.")
    members = market_members(db, m.id)
    clusters = db.query(AIPromptCluster).filter(
        AIPromptCluster.market_id == m.id, AIPromptCluster.property_id.is_(None)
    ).order_by(AIPromptCluster.scope, AIPromptCluster.importance.desc()).all()
    return {
        "id": m.id, "slug": m.slug, "name": m.name, "city": m.city, "state": m.state,
        "properties": [{"id": p.id, "name": p.name} for p in members],
        "clusters": [_cluster_out(c) for c in clusters],
    }


@router.get("/prompts")
def list_prompts(
    property_id: int | None = Query(default=None),
    market_id: int | None = Query(default=None),
    scope: str | None = Query(default=None),
    include_variants: bool = Query(default=True),
    db: Session = Depends(get_db),
):
    if property_id is None and market_id is None:
        raise HTTPException(status_code=422, detail="property_id or market_id is required.")
    q = db.query(AIVisibilityPrompt)
    if property_id is not None:
        prop = db.get(Property, property_id)
        if prop is None:
            raise HTTPException(status_code=404, detail="Property not found.")
        # A property's universe = its brand prompts + its market's shared prompts.
        cond = AIVisibilityPrompt.property_id == property_id
        if prop.market_id is not None:
            cond = cond | ((AIVisibilityPrompt.market_id == prop.market_id) & AIVisibilityPrompt.property_id.is_(None))
        q = q.filter(cond)
    else:
        q = q.filter(AIVisibilityPrompt.market_id == market_id, AIVisibilityPrompt.property_id.is_(None))
    if scope:
        q = q.filter(AIVisibilityPrompt.scope == scope)
    if not include_variants:
        q = q.filter(AIVisibilityPrompt.is_representative.is_(True))
    rows = q.order_by(AIVisibilityPrompt.scope, AIVisibilityPrompt.importance.desc(), AIVisibilityPrompt.id).all()
    return {"prompts": [_prompt_out(p) for p in rows], "total": len(rows)}


class PromptIn(BaseModel):
    prompt_text: str
    scope: str = "brand"
    platform: str = "chatgpt"
    property_id: int | None = None
    market_id: int | None = None
    topic_key: str | None = None
    intent: str | None = None
    importance: int = 3
    repeat_count: int = 1


@router.post("/prompts", status_code=201)
def create_prompt(payload: PromptIn, db: Session = Depends(get_db)):
    text = (payload.prompt_text or "").strip()
    if not text:
        raise HTTPException(status_code=422, detail="Prompt text is empty.")
    if payload.scope not in PROMPT_SCOPES:
        raise HTTPException(status_code=422, detail=f"scope must be one of {', '.join(PROMPT_SCOPES)}.")
    try:
        platform = validate_platform(payload.platform)
    except InvalidPlatformError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    if payload.scope in ("brand", "sentinel") and payload.property_id is None:
        raise HTTPException(status_code=422, detail="Brand and sentinel prompts need a property_id.")
    if payload.scope in ("market", "feature") and payload.market_id is None:
        raise HTTPException(status_code=422, detail="Market and feature prompts need a market_id.")
    org_id = property_org_id(db, payload.property_id) if payload.property_id else None
    draft = PromptDraft(
        text=text, scope=payload.scope, topic_key=payload.topic_key, intent=payload.intent,
        importance=max(1, min(5, payload.importance)), funnel_stage=None,
        variant_group=f"manual:{payload.property_id or ''}:{payload.market_id or ''}",
        is_representative=True, generated_from={"generation_method": "manual"},
        generation_method="manual", market_id=payload.market_id, property_id=payload.property_id,
        organization_id=org_id, platform=platform,
    )
    row, created = upsert_prompt(db, draft)
    row.repeat_count = max(1, min(5, payload.repeat_count))
    db.commit()
    return {"prompt": _prompt_out(row), "created": created}


class PromptPatch(BaseModel):
    active: bool | None = None
    approved: bool | None = None
    importance: int | None = None
    repeat_count: int | None = None
    scope: str | None = None
    topic_key: str | None = None


@router.patch("/prompts/{prompt_id}")
def update_prompt(prompt_id: int, payload: PromptPatch, db: Session = Depends(get_db)):
    row = db.get(AIVisibilityPrompt, prompt_id)
    if row is None:
        raise HTTPException(status_code=404, detail="Prompt not found.")
    changes = payload.model_dump(exclude_unset=True)
    if "scope" in changes and changes["scope"] not in PROMPT_SCOPES:
        raise HTTPException(status_code=422, detail=f"scope must be one of {', '.join(PROMPT_SCOPES)}.")
    for k, v in changes.items():
        if k in ("importance", "repeat_count") and v is not None:
            v = max(1, min(5, int(v)))
        setattr(row, k, v)
    db.commit()
    return {"prompt": _prompt_out(row)}


@router.post("/prompts/generate")
def generate(property_id: int = Query(...), db: Session = Depends(get_db)):
    """Build the property's prompt universe: brand prompts, the shared market
    universe, clusters for both, and the property's assignments. Idempotent."""
    if db.get(Property, property_id) is None:
        raise HTTPException(status_code=404, detail="Property not found.")
    try:
        gen = generate_property_prompts(db, property_id)
        brand_report = cluster_prompts(db, property_id=property_id)
        market_report = cluster_prompts(db, market_id=gen["market_id"]) if gen["market_id"] else None
        subs = subscribe_property(db, property_id)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return {
        "property_id": property_id,
        "market_id": gen["market_id"],
        "brand_prompts": {"total": gen["brand_prompts_total"], "created": gen["brand_prompts_created"]},
        "market_prompts": {"total": gen["market_prompts_total"], "created": gen["market_prompts_created"]},
        "clusters": {
            "brand": brand_report.clusters_total,
            "market": market_report.clusters_total if market_report else 0,
            "embedding_model": brand_report.embedded_model,
        },
        "assignments": subs,
        "signal_topics": gen["signal_topics"],
    }


@router.post("/prompts/cluster")
def recluster(
    property_id: int | None = Query(default=None),
    market_id: int | None = Query(default=None),
    db: Session = Depends(get_db),
):
    if property_id is None and market_id is None:
        raise HTTPException(status_code=422, detail="property_id or market_id is required.")
    report = cluster_prompts(db, property_id=property_id, market_id=market_id)
    return {
        "clusters_total": report.clusters_total, "clusters_created": report.clusters_created,
        "prompts_clustered": report.prompts_clustered, "embedding_model": report.embedded_model,
        "buckets": report.buckets,
    }


@router.get("/clusters")
def list_clusters(
    property_id: int | None = Query(default=None),
    market_id: int | None = Query(default=None),
    db: Session = Depends(get_db),
):
    if property_id is None and market_id is None:
        raise HTTPException(status_code=422, detail="property_id or market_id is required.")
    q = db.query(AIPromptCluster)
    if property_id is not None:
        prop = db.get(Property, property_id)
        if prop is None:
            raise HTTPException(status_code=404, detail="Property not found.")
        assigned = {a.cluster_id for a in assignments_for_property(db, property_id)}
        cond = AIPromptCluster.property_id == property_id
        if prop.market_id is not None:
            cond = cond | ((AIPromptCluster.market_id == prop.market_id) & AIPromptCluster.property_id.is_(None))
        rows = q.filter(cond).order_by(AIPromptCluster.scope, AIPromptCluster.importance.desc()).all()
        out = [{**_cluster_out(c), "assigned": c.id in assigned} for c in rows]
    else:
        rows = q.filter(AIPromptCluster.market_id == market_id, AIPromptCluster.property_id.is_(None)).all()
        out = [_cluster_out(c) for c in rows]
    return {"clusters": out, "total": len(out)}


# --- Slice 3: shared market scoring, metrics, rollups -----------------------

MAX_PAGE = 200


def _require_property(db: Session, property_id: int) -> Property:
    prop = db.get(Property, property_id)
    if prop is None:
        raise HTTPException(status_code=404, detail="Property not found.")
    return prop


def _today(today: date | None) -> date:
    return today or datetime.now(timezone.utc).date()


@router.get("/meta")
def observatory_meta():
    return {
        "metrics": METRIC_DEFINITIONS,
        "data_labels": [LABEL_OBSERVED, LABEL_MEASURED, LABEL_MODELED, LABEL_UNAVAILABLE],
        "opportunity_score": {
            "weights": opportunity_weights(),
            "note": "Beacon Prompt Opportunity Score is MODELED (0-100). It is not prompt search volume.",
        },
        "limitations": [
            "AI platforms do not publish prompt volume; Beacon never reports AI search volume.",
            "Monitoring runs are Beacon's own API calls, not consumer impressions.",
            "Retrieval queries are what the provider reported issuing for Beacon's call, not what renters typed.",
            "Recommendation Rate is MODELED by a rule-based classifier.",
        ],
    }


@router.get("/overview")
def overview(
    property_id: int = Query(...),
    days: int = Query(default=30, ge=1, le=365),
    platform: str = Query(default=PLATFORM_ALL),
    today: date | None = Query(default=None),
    db: Session = Depends(get_db),
):
    prop = _require_property(db, property_id)
    end = _today(today)
    start = end - timedelta(days=days - 1)
    prev_start, prev_end = previous_window(start, end)
    current = metrics_for_window(db, property_id, start, end, platform)
    previous = metrics_for_window(db, property_id, prev_start, prev_end, platform)
    keys = ["ai_visibility", "citation_rate", "citation_share", "share_of_voice",
            "recommendation_rate", "competitor_win_rate"]
    metrics = {k: {**current[k], "comparison": compare_points(current[k]["value"], previous[k]["value"])} for k in keys}
    cov = prompt_coverage(db, property_id, start, end)
    prev_cov = prompt_coverage(db, property_id, prev_start, prev_end)
    metrics["prompt_coverage"] = {**cov, "comparison": compare_points(cov["value"], prev_cov["value"])}
    counts = current["counts"]
    return {
        "property_id": prop.id,
        "property_name": prop.name,
        "market_id": prop.market_id,
        "window": {"start": start.isoformat(), "end": end.isoformat(), "days": days},
        "previous_window": {"start": prev_start.isoformat(), "end": prev_end.isoformat()},
        "platform": platform,
        "metrics": metrics,
        "sentiment": {
            "data_label": LABEL_MODELED,
            "positive": counts["sentiment_pos"], "neutral": counts["sentiment_neu"],
            "negative": counts["sentiment_neg"],
        },
        "sample": {"eligible_responses": counts["eligible_count"], "observations": counts["runs_count"]},
        "top_sources": source_influence(db, property_id, start, end, limit=5),
    }


@router.get("/trends")
def trends(
    property_id: int = Query(...),
    metric: str = Query(default="ai_visibility"),
    days: int = Query(default=30, ge=1, le=365),
    platform: str = Query(default=PLATFORM_ALL),
    today: date | None = Query(default=None),
    db: Session = Depends(get_db),
):
    _require_property(db, property_id)
    if metric not in METRIC_DEFINITIONS or metric == "source_influence":
        raise HTTPException(status_code=422, detail=f"Unknown metric '{metric}'.")
    return trend(db, property_id, metric, days, _today(today), platform)


@router.get("/sources")
def sources(
    property_id: int = Query(...),
    days: int = Query(default=30, ge=1, le=365),
    limit: int = Query(default=25, ge=1, le=MAX_PAGE),
    today: date | None = Query(default=None),
    db: Session = Depends(get_db),
):
    _require_property(db, property_id)
    end = _today(today)
    return source_influence(db, property_id, end - timedelta(days=days - 1), end, limit=limit)


@router.get("/citations")
def citations(
    property_id: int = Query(...),
    days: int = Query(default=30, ge=1, le=365),
    domain: str | None = Query(default=None),
    source_type: str | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=MAX_PAGE),
    offset: int = Query(default=0, ge=0),
    today: date | None = Query(default=None),
    db: Session = Depends(get_db),
):
    """Every citation in the property's eligible responses, newest first,
    paginated. OBSERVED: exactly what the provider (or the response text)
    reported."""
    prop = _require_property(db, property_id)
    end = _today(today)
    start_dt = datetime.combine(end - timedelta(days=days - 1), datetime.min.time())
    end_dt = datetime.combine(end + timedelta(days=1), datetime.min.time())
    q = (
        db.query(AICitation, AIPropertyObservation)
        .join(AIPropertyObservation, AIPropertyObservation.response_id == AICitation.response_id)
        .filter(
            AIPropertyObservation.property_id == property_id,
            AIPropertyObservation.observed_at >= start_dt,
            AIPropertyObservation.observed_at < end_dt,
        )
    )
    if domain:
        q = q.filter(AICitation.domain == domain.lower())
    if source_type:
        q = q.filter(AICitation.source_type == source_type)
    total = q.count()
    rows = q.order_by(AIPropertyObservation.observed_at.desc(), AICitation.citation_order).offset(offset).limit(limit).all()
    owned = {prop.domain} if prop.domain else set()
    return {
        "data_label": LABEL_OBSERVED,
        "total": total, "limit": limit, "offset": offset,
        "items": [
            {
                "citation_id": c.id, "response_id": c.response_id, "run_id": c.run_id,
                "url": c.url, "domain": c.domain, "title": c.title, "order": c.citation_order,
                "source_type": c.source_type, "capture_method": c.capture_method,
                "owned": c.domain in owned or any(c.domain.endswith("." + d) for d in owned),
                "platform": o.platform, "observed_at": o.observed_at.isoformat(),
                "prompt_id": o.prompt_id, "cluster_id": o.cluster_id,
            }
            for c, o in rows
        ],
    }


@router.get("/observations")
def observations(
    property_id: int = Query(...),
    cluster_id: int | None = Query(default=None),
    limit: int = Query(default=50, ge=1, le=MAX_PAGE),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    """Raw derived observations (the evidence behind every KPI), paginated."""
    _require_property(db, property_id)
    q = db.query(AIPropertyObservation).filter(AIPropertyObservation.property_id == property_id)
    if cluster_id is not None:
        q = q.filter(AIPropertyObservation.cluster_id == cluster_id)
    total = q.count()
    rows = q.order_by(AIPropertyObservation.observed_at.desc(), AIPropertyObservation.id.desc()).offset(offset).limit(limit).all()
    return {"total": total, "limit": limit, "offset": offset, "items": [_observation_out(o) for o in rows]}


def _observation_out(o: AIPropertyObservation) -> dict:
    return {
        "id": o.id, "response_id": o.response_id, "run_id": o.run_id, "prompt_id": o.prompt_id,
        "cluster_id": o.cluster_id, "market_id": o.market_id, "platform": o.platform,
        "observed_at": o.observed_at.isoformat(), "eligibility_reason": o.eligibility_reason,
        "mentioned": o.mentioned, "mention_rank": o.mention_rank, "mention_confidence": o.mention_confidence,
        "cited": o.cited, "citation_count": o.citation_count,
        "recommended": o.recommended, "recommendation_method": o.recommendation_method,
        "sentiment": o.sentiment, "context_excerpt": o.context_excerpt,
        "competitor_mentioned_count": o.competitor_mentioned_count,
        "competitor_cited_count": o.competitor_cited_count,
        "total_citation_count": o.total_citation_count,
    }


@router.get("/clusters/{cluster_id}/opportunity")
def cluster_opportunity(
    cluster_id: int,
    property_id: int = Query(...),
    days: int = Query(default=30, ge=1, le=365),
    today: date | None = Query(default=None),
    db: Session = Depends(get_db),
):
    _require_property(db, property_id)
    try:
        return prompt_opportunity_score(db, property_id, cluster_id, days=days, today=_today(today))
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc))


@router.get("/markets/{market_id}/summary")
def market_summary(
    market_id: int,
    days: int = Query(default=30, ge=1, le=365),
    today: date | None = Query(default=None),
    db: Session = Depends(get_db),
):
    """Shared market view: how many observations the market's runs
    produced and how each member property fared in them."""
    m = db.get(Market, market_id)
    if m is None:
        raise HTTPException(status_code=404, detail="Market not found.")
    end = _today(today)
    start = end - timedelta(days=days - 1)
    daily = db.query(AIMarketDaily).filter(
        AIMarketDaily.market_id == market_id, AIMarketDaily.day >= start, AIMarketDaily.day <= end
    ).all()
    members = market_members(db, market_id)
    leaderboard = []
    for p in members:
        mm = metrics_for_window(db, p.id, start, end)
        leaderboard.append({
            "property_id": p.id, "name": p.name,
            "ai_visibility": mm["ai_visibility"]["value"],
            "citation_rate": mm["citation_rate"]["value"],
            "share_of_voice": mm["share_of_voice"]["value"],
            "eligible_responses": mm["counts"]["eligible_count"],
        })
    leaderboard.sort(key=lambda r: (r["ai_visibility"] is None, -(r["ai_visibility"] or 0), r["name"]))
    return {
        "market": {"id": m.id, "slug": m.slug, "name": m.name},
        "window": {"start": start.isoformat(), "end": end.isoformat(), "days": days},
        "runs": sum(d.runs_count for d in daily),
        "responses": sum(d.responses_count for d in daily),
        "properties_scored": sum(d.properties_scored for d in daily),
        "citations": sum(d.citations_count for d in daily),
        "data_label": LABEL_MEASURED,
        "note": "One market answer scores every subscribed property; runs are Beacon monitoring calls, not consumer impressions.",
        "leaderboard": leaderboard,
    }


@router.post("/prompts/{prompt_id}/run")
def run_market_prompt(
    prompt_id: int,
    platform: str | None = Query(default=None),
    db: Session = Depends(get_db),
):
    """Enqueue one shared market run (the jobs runner executes it)."""
    prompt = db.get(AIVisibilityPrompt, prompt_id)
    if prompt is None:
        raise HTTPException(status_code=404, detail="Prompt not found.")
    if prompt.property_id is not None or prompt.market_id is None:
        raise HTTPException(status_code=422, detail="Only market-scope prompts run as shared market runs.")
    try:
        plat = validate_platform(platform or prompt.platform)
    except InvalidPlatformError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    job, created = enqueue(
        db, "execute_market_run", {"prompt_id": prompt.id, "platform": plat},
        idempotency_key=f"execute_market_run:{prompt.id}:{plat}:{_today(None).isoformat()}:manual",
        market_id=prompt.market_id, organization_id=prompt.organization_id,
    )
    db.commit()
    return {"job_id": job.id, "status": job.status, "created": created}


@router.post("/rollups/rebuild")
def rollups_rebuild(property_id: int | None = Query(default=None), db: Session = Depends(get_db)):
    ids = [property_id] if property_id is not None else None
    derived = backfill_observations(db, property_id=property_id)
    rolled = rebuild_rollups(db, property_ids=ids)
    return {"derived": derived, "rollups": rolled}
