"""Content Intelligence API. GET returns the live deterministic analysis;
POST /analyze also enqueues a content sync so Nora's Content Intelligence chunk
refreshes. No external AI is called for analysis."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import get_db
from app.extensions.hooks import trigger_rag_sync
from app.models import Property
from app.services.content_intelligence import analyze_property

router = APIRouter(prefix="/content-intelligence", tags=["content-intelligence"])


@router.get("/{property_id}")
def get_analysis(property_id: int, db: Session = Depends(get_db)):
    if db.get(Property, property_id) is None:
        raise HTTPException(status_code=404, detail="Property not found.")
    return analyze_property(db, property_id)


@router.post("/{property_id}/analyze")
def analyze(property_id: int, db: Session = Depends(get_db)):
    if db.get(Property, property_id) is None:
        raise HTTPException(status_code=404, detail="Property not found.")
    analysis = analyze_property(db, property_id)
    # Refresh the Content Intelligence chunk so Nora reflects the latest content.
    job = trigger_rag_sync(
        db, property_id=property_id, source="content", reason="content_intelligence_analyze"
    )
    return {"analysis": analysis, "sync_job_id": job.id}
