"""Competitor Intelligence API (Phase 13): deterministic AI-answer share of
voice over operator-named competitors. GET returns the live analysis; POST
/analyze also enqueues a sync so Nora's chunk refreshes."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import get_db
from app.extensions.hooks import trigger_rag_sync
from app.models import Property
from app.services.competitor_intelligence import analyze_share_of_voice

router = APIRouter(prefix="/competitor-intelligence", tags=["competitor-intelligence"])


@router.get("/{property_id}")
def get_analysis(property_id: int, db: Session = Depends(get_db)):
    if db.get(Property, property_id) is None:
        raise HTTPException(status_code=404, detail="Property not found.")
    return analyze_share_of_voice(db, property_id)


@router.post("/{property_id}/analyze")
def analyze(property_id: int, db: Session = Depends(get_db)):
    if db.get(Property, property_id) is None:
        raise HTTPException(status_code=404, detail="Property not found.")
    result = analyze_share_of_voice(db, property_id)
    job = trigger_rag_sync(
        db, property_id=property_id, source="competitors",
        reason="competitor_intelligence_analyze",
    )
    return {"analysis": result, "sync_job_id": job.id}
