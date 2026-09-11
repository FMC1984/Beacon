"""AI Visibility Observatory API (Phase 19).

Slice 2 surface: the prompt library (generate, list, create, edit, cluster)
and markets. Later slices add overview, citations, sources, competitors,
recommendations, accuracy, trends, costs and schedule here.
"""

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import AIPromptCluster, AIVisibilityPrompt, Market, Property
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
from app.services.observatory.taxonomy import topics
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
