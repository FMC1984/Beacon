"""Opportunity Engine API: one unified, prioritized, context-gated view of every
module's recommendations. Deterministic; interpretation happens in the analyzers
this aggregates, not here."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import get_db
from app.extensions.hooks import trigger_rag_sync
from app.models import Property
from app.services.opportunity_engine import build_opportunities

router = APIRouter(prefix="/opportunities", tags=["opportunities"])


@router.get("/{property_id}")
def get_opportunities(property_id: int, db: Session = Depends(get_db)):
    if db.get(Property, property_id) is None:
        raise HTTPException(status_code=404, detail="Property not found.")
    return build_opportunities(db, property_id)


@router.post("/{property_id}/analyze")
def analyze(property_id: int, db: Session = Depends(get_db)):
    if db.get(Property, property_id) is None:
        raise HTTPException(status_code=404, detail="Property not found.")
    result = build_opportunities(db, property_id)
    job = trigger_rag_sync(
        db, property_id=property_id, source="content",
        reason="opportunity_engine_analyze",
    )
    return {"analysis": result, "sync_job_id": job.id}
