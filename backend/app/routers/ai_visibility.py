"""AI Visibility Foundation API (Phase 11.5).

Execute an external-AI query (subject to a per-property daily budget), and read
stored results. Query execution is the only non-deterministic step; parsing of
the stored response is deterministic. Analysis/scoring/recommendations are
Phase 12 and deliberately absent here.
"""

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db import get_db
from app.extensions.hooks import trigger_rag_sync
from app.models import AITopic, AIVisibilityPrompt, AIVisibilityQuery, Property
from app.providers.base import MissingAPIKeyError
from app.schemas.ai_visibility import AIVisibilityQueryIn, AIVisibilityQueryOut
from app.services.ai_visibility.analyzer import analyze_ai_visibility
from app.services.ai_visibility.execution import RateLimitExceeded, budget_status, run_query
from app.services.ai_visibility.hallucination import check_response_against_context
from app.services.ai_visibility.providers import PlatformNotConnectedError, provider_name
from app.services.ai_visibility.schedule import (
    prompt_suggestions,
    run_standing_prompts,
    score_history,
)
from app.services.ai_visibility.reference import (
    InvalidPlatformError,
    methodology,
    platforms,
)
from app.services.property_context import get_property_context

router = APIRouter(prefix="/ai-visibility", tags=["ai-visibility"])


def _require_property(db: Session, property_id: int) -> Property:
    prop = db.get(Property, property_id)
    if prop is None:
        raise HTTPException(status_code=404, detail="Property not found.")
    return prop


@router.get("/meta")
def meta():
    """Platform vocabulary, the documented query methodology, and the active
    provider. Exposed so the methodology is visible in the product, not just in
    code (the transparency gap the spec calls out)."""
    return {
        "platforms": platforms(),
        "methodology": methodology(),
        "provider": provider_name(),
    }


@router.post("/{property_id}/query")
def execute(property_id: int, payload: AIVisibilityQueryIn, db: Session = Depends(get_db)):
    _require_property(db, property_id)
    try:
        row = run_query(db, property_id, payload.prompt, payload.platform)
    except InvalidPlatformError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except RateLimitExceeded as exc:
        raise HTTPException(status_code=429, detail=str(exc))
    except PlatformNotConnectedError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    except MissingAPIKeyError as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    return {
        "query": AIVisibilityQueryOut.model_validate(row),
        "budget": budget_status(db, property_id),
    }


@router.get("/{property_id}/analysis")
def analysis(property_id: int, db: Session = Depends(get_db)):
    """Phase 12 deterministic AI Visibility analysis: per-platform mention rates,
    source landscape, interpreted fact-checks, an explainable (sample-gated)
    score, and gated recommendations."""
    _require_property(db, property_id)
    return analyze_ai_visibility(db, property_id)


@router.post("/{property_id}/analyze")
def analyze(property_id: int, db: Session = Depends(get_db)):
    _require_property(db, property_id)
    result = analyze_ai_visibility(db, property_id)
    job = trigger_rag_sync(
        db, property_id=property_id, source="ai_visibility",
        reason="ai_visibility_analyze",
    )
    return {"analysis": result, "sync_job_id": job.id}


@router.get("/{property_id}")
def list_queries(
    property_id: int,
    platform: str | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    _require_property(db, property_id)
    q = db.query(AIVisibilityQuery).filter_by(property_id=property_id)
    if platform is not None:
        q = q.filter(AIVisibilityQuery.platform == platform)
    if date_from is not None:
        q = q.filter(AIVisibilityQuery.executed_at >= date_from)
    if date_to is not None:
        # inclusive of the whole to-day
        from datetime import datetime, time

        q = q.filter(AIVisibilityQuery.executed_at <= datetime.combine(date_to, time.max))
    rows = (
        q.order_by(AIVisibilityQuery.executed_at.desc(), AIVisibilityQuery.id.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )
    return {
        "queries": [AIVisibilityQueryOut.model_validate(r) for r in rows],
        "budget": budget_status(db, property_id),
        "provider": provider_name(),
    }


# --- standing prompts + scheduled scoring (registered before the
# /{property_id}/{query_id} catch-all so string paths match cleanly) ---


class PromptIn(BaseModel):
    prompt_text: str
    platform: str = "chatgpt"
    topic_id: int | None = None
    audience: str | None = None
    persona: str | None = None
    location_market: str | None = None
    priority: str | None = None
    tags: list[str] | None = None


@router.post("/{property_id}/import-question-set")
def import_prompts_question_set(
    property_id: int, payload: dict, db: Session = Depends(get_db)
):
    """Import an operator-authored question-set JSON (the dchp-beacon-queries
    shape): questions become cadence-aware standing prompts (upserted by text,
    so re-importing a revision updates instead of duplicating) and named
    organization competitors become Competitor rows."""
    from app.services.ai_visibility.question_set import import_question_set

    _require_property(db, property_id)
    try:
        return import_question_set(db, property_id, payload)
    except ValueError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.get("/{property_id}/prompts")
def list_prompts(property_id: int, db: Session = Depends(get_db)):
    _require_property(db, property_id)
    rows = (
        db.query(AIVisibilityPrompt)
        .filter_by(property_id=property_id)
        .order_by(AIVisibilityPrompt.id)
        .all()
    )
    return {
        "prompts": [
            {
                "id": r.id,
                "prompt_text": r.prompt_text,
                "platform": r.platform,
                "active": r.active,
                "cadence": r.cadence,
                "runs_per_cycle": r.runs_per_cycle,
                "volatile": r.volatile,
                "owning_url": r.owning_url,
                "last_run_at": r.last_run_at.isoformat() if r.last_run_at else None,
                "topic_id": r.topic_id,
                "audience": r.audience,
                "persona": r.persona,
                "location_market": r.location_market,
                "priority": r.priority,
                "tags": r.tags,
            }
            for r in rows
        ],
        "budget": budget_status(db, property_id),
    }


@router.get("/{property_id}/topics")
def list_topics(property_id: int, db: Session = Depends(get_db)):
    _require_property(db, property_id)
    rows = (
        db.query(AITopic)
        .filter_by(property_id=property_id)
        .order_by(AITopic.topic_name)
        .all()
    )
    return {
        "topics": [
            {
                "id": t.id, "topic_name": t.topic_name, "description": t.description,
                "priority": t.priority, "status": t.status,
            }
            for t in rows
        ]
    }


class TopicIn(BaseModel):
    topic_name: str
    description: str | None = None
    priority: str = "medium"


@router.post("/{property_id}/topics", status_code=201)
def add_topic(property_id: int, payload: TopicIn, db: Session = Depends(get_db)):
    _require_property(db, property_id)
    name = (payload.topic_name or "").strip()
    if not name:
        raise HTTPException(status_code=422, detail="Topic name is empty.")
    row = AITopic(
        property_id=property_id, topic_name=name,
        description=payload.description, priority=payload.priority,
    )
    db.add(row)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="A topic with this name already exists.")
    db.refresh(row)
    return {
        "id": row.id, "topic_name": row.topic_name, "description": row.description,
        "priority": row.priority, "status": row.status,
    }


@router.delete("/{property_id}/topics/{topic_id}")
def delete_topic(property_id: int, topic_id: int, db: Session = Depends(get_db)):
    row = db.query(AITopic).filter_by(id=topic_id, property_id=property_id).one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Topic not found.")
    db.delete(row)
    db.commit()
    return {"ok": True}


@router.get("/{property_id}/prompt-suggestions")
def suggestions(property_id: int, db: Session = Depends(get_db)):
    prop = _require_property(db, property_id)
    return {"suggestions": prompt_suggestions(prop)}


@router.post("/{property_id}/prompts", status_code=201)
def add_prompt(property_id: int, payload: PromptIn, db: Session = Depends(get_db)):
    _require_property(db, property_id)
    text = (payload.prompt_text or "").strip()
    if not text:
        raise HTTPException(status_code=422, detail="Prompt text is empty.")
    row = AIVisibilityPrompt(
        property_id=property_id, prompt_text=text, platform=payload.platform,
        topic_id=payload.topic_id, audience=payload.audience, persona=payload.persona,
        location_market=payload.location_market, priority=payload.priority,
        tags=payload.tags,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    return {
        "id": row.id, "prompt_text": row.prompt_text, "platform": row.platform,
        "active": row.active, "topic_id": row.topic_id, "audience": row.audience,
        "persona": row.persona, "location_market": row.location_market,
        "priority": row.priority, "tags": row.tags,
    }


@router.delete("/{property_id}/prompts/{prompt_id}")
def delete_prompt(property_id: int, prompt_id: int, db: Session = Depends(get_db)):
    row = db.query(AIVisibilityPrompt).filter_by(id=prompt_id, property_id=property_id).one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="Prompt not found.")
    db.delete(row)
    db.commit()
    return {"ok": True}


@router.post("/{property_id}/run-standing")
def run_standing(property_id: int, db: Session = Depends(get_db)):
    """Run every active standing prompt now, then snapshot the score. This
    spends OpenAI budget; it is user-initiated (a button) or scheduled."""
    _require_property(db, property_id)
    try:
        result = run_standing_prompts(db, property_id)
    except PlatformNotConnectedError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    except MissingAPIKeyError as exc:
        raise HTTPException(status_code=400, detail=str(exc))
    return result


@router.get("/{property_id}/score-history")
def get_score_history(property_id: int, db: Session = Depends(get_db)):
    _require_property(db, property_id)
    return {"history": score_history(db, property_id)}


@router.post("/{property_id}/backfill-mentions")
def backfill_property_mentions(property_id: int, db: Session = Depends(get_db)):
    """One-time (safely re-runnable) pass over this property's existing
    AIVisibilityQuery history to populate Share of Voice Mention rows, so
    trend/history reporting has real data instead of starting empty. Cheap
    and purely deterministic (no external calls) - operator-triggered."""
    from app.services.ai_visibility.mentions import backfill_mentions

    _require_property(db, property_id)
    return backfill_mentions(db, property_id=property_id)


@router.get("/{property_id}/{query_id}")
def get_query(property_id: int, query_id: int, db: Session = Depends(get_db)):
    prop = _require_property(db, property_id)
    row = (
        db.query(AIVisibilityQuery)
        .filter_by(id=query_id, property_id=property_id)
        .one_or_none()
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Query not found.")
    context = get_property_context(db, property_id)
    return {
        "query": AIVisibilityQueryOut.model_validate(row),
        # The hallucination-check hook's output for this stored response (a flag
        # with a reason; interpretation is Phase 12).
        "fact_check": check_response_against_context(
            row.raw_response_text, prop, context
        ),
    }
