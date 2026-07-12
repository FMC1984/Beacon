"""AI Visibility Foundation API (Phase 11.5).

Execute an external-AI query (subject to a per-property daily budget), and read
stored results. Query execution is the only non-deterministic step; parsing of
the stored response is deterministic. Analysis/scoring/recommendations are
Phase 12 and deliberately absent here.
"""

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.db import get_db
from app.extensions.hooks import trigger_rag_sync
from app.models import AIVisibilityQuery, Property
from app.providers.base import MissingAPIKeyError
from app.schemas.ai_visibility import AIVisibilityQueryIn, AIVisibilityQueryOut
from app.services.ai_visibility.analyzer import analyze_ai_visibility
from app.services.ai_visibility.execution import RateLimitExceeded, budget_status, run_query
from app.services.ai_visibility.hallucination import check_response_against_context
from app.services.ai_visibility.providers import PlatformNotConnectedError, provider_name
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
