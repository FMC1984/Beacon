"""AI Query Signals API.

GET returns the live deterministic three-tier analysis (observed / search-
adjacent / inferred) for a property, with optional date-range, platform, and
landing-page filters. POST /analyze also enqueues a sync so Nora's
`ai_query_signals` chunk refreshes. No external AI is called; exact LLM prompts
are never claimed or fabricated.
"""

from datetime import date

from fastapi import APIRouter, Depends, HTTPException, Query
from sqlalchemy.orm import Session

from app.db import get_db
from app.extensions.hooks import trigger_rag_sync
from app.models import Property
from app.services.ai_query_signals import analyze_ai_query_signals

router = APIRouter(prefix="/ai-query-signals", tags=["ai-query-signals"])


def _parse_date(value: str | None, label: str) -> date | None:
    if value is None:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        raise HTTPException(status_code=422, detail=f"{label} must be YYYY-MM-DD.")


@router.get("/{property_id}")
def get_signals(
    property_id: int,
    start: str | None = Query(default=None, description="ISO date, inclusive"),
    end: str | None = Query(default=None, description="ISO date, inclusive"),
    platform: str | None = Query(default=None, description="AI platform key filter"),
    landing_page: str | None = Query(default=None, description="Landing page filter"),
    db: Session = Depends(get_db),
):
    if db.get(Property, property_id) is None:
        raise HTTPException(status_code=404, detail="Property not found.")
    return analyze_ai_query_signals(
        db,
        property_id,
        start=_parse_date(start, "start"),
        end=_parse_date(end, "end"),
        platform=platform,
        landing_page=landing_page,
    )


@router.post("/{property_id}/analyze")
def analyze(property_id: int, db: Session = Depends(get_db)):
    if db.get(Property, property_id) is None:
        raise HTTPException(status_code=404, detail="Property not found.")
    analysis = analyze_ai_query_signals(db, property_id)
    # Refresh the AI Query Signals chunk so Nora reflects the latest signals.
    job = trigger_rag_sync(
        db, property_id=property_id, source="ga4", reason="ai_query_signals_analyze"
    )
    return {"analysis": analysis, "sync_job_id": job.id}
