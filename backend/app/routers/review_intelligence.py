"""Review Intelligence API. GET returns the live deterministic analysis; POST
/analyze also enqueues a review sync so Nora's Review Intelligence chunk
refreshes. No external AI is called for analysis."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import get_db
from app.extensions.hooks import trigger_rag_sync
from app.models import Property
from app.services.review_intelligence import analyze_property_reviews

router = APIRouter(prefix="/review-intelligence", tags=["review-intelligence"])


@router.get("/{property_id}")
def get_analysis(property_id: int, db: Session = Depends(get_db)):
    if db.get(Property, property_id) is None:
        raise HTTPException(status_code=404, detail="Property not found.")
    return analyze_property_reviews(db, property_id)


@router.post("/{property_id}/analyze")
def analyze(property_id: int, db: Session = Depends(get_db)):
    if db.get(Property, property_id) is None:
        raise HTTPException(status_code=404, detail="Property not found.")
    analysis = analyze_property_reviews(db, property_id)
    job = trigger_rag_sync(
        db, property_id=property_id, source="reviews", reason="review_intelligence_analyze"
    )
    return {"analysis": analysis, "sync_job_id": job.id}
