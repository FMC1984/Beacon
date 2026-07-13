"""Review CRUD. Manual entry / import for now (no scraping). Any create, update,
or delete enqueues the existing RAG sync (source "reviews"), which refreshes the
per-review chunks and the derived Review Intelligence chunk and removes the
chunk of a deleted review."""

from datetime import date, datetime, timezone

from fastapi import (
    APIRouter,
    BackgroundTasks,
    Depends,
    Form,
    HTTPException,
    Query,
    UploadFile,
)
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db
from app.extensions.hooks import trigger_rag_sync
from app.models import Property, PropertyReview
from app.schemas.reviews import ReviewIn, ReviewOut
from app.services.ingestion.common import UploadValidationError
from app.services.ingestion.reviews import ingest_reviews
from app.services.rag_sync_service import drain_queue

router = APIRouter(prefix="/reviews", tags=["reviews"])


def _require_property(db: Session, property_id: int):
    if db.get(Property, property_id) is None:
        raise HTTPException(status_code=404, detail="Property not found.")


@router.get("/{property_id}", response_model=list[ReviewOut])
def list_reviews(
    property_id: int,
    provider: str | None = None,
    min_rating: float | None = None,
    max_rating: float | None = None,
    date_from: date | None = None,
    date_to: date | None = None,
    limit: int = Query(default=200, ge=1, le=1000),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
):
    _require_property(db, property_id)
    q = db.query(PropertyReview).filter_by(property_id=property_id)
    if provider is not None:
        q = q.filter(PropertyReview.provider == provider)
    if min_rating is not None:
        q = q.filter(PropertyReview.rating >= min_rating)
    if max_rating is not None:
        q = q.filter(PropertyReview.rating <= max_rating)
    if date_from is not None:
        q = q.filter(PropertyReview.review_date >= date_from)
    if date_to is not None:
        q = q.filter(PropertyReview.review_date <= date_to)
    return (
        q.order_by(PropertyReview.review_date.desc(), PropertyReview.id.desc())
        .offset(offset)
        .limit(limit)
        .all()
    )


@router.post("/{property_id}", response_model=ReviewOut, status_code=201)
def create_review(property_id: int, payload: ReviewIn, db: Session = Depends(get_db)):
    _require_property(db, property_id)
    review = PropertyReview(property_id=property_id, **payload.model_dump())
    db.add(review)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=409,
            detail="A review with this provider and external_review_id already exists.",
        )
    db.refresh(review)
    trigger_rag_sync(db, property_id=property_id, source="reviews", reason="review_create")
    return review


@router.post("/{property_id}/import", status_code=201)
async def import_reviews(
    property_id: int,
    background: BackgroundTasks,
    file: UploadFile,
    provider: str = Form("google"),
    db: Session = Depends(get_db),
):
    """Bulk-import reviews from a CSV export (the working path for Google
    Business Profile reviews until the live connector is API-approved). Tolerant
    of column naming; upserts by (provider, external_review_id) so re-imports
    update rather than duplicate. One RAG sync refreshes the review chunks and
    the derived Review Intelligence chunk for the whole batch."""
    _require_property(db, property_id)
    data = await file.read()
    try:
        summary = ingest_reviews(db, property_id, data, provider)
    except UploadValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc))
    db.commit()
    job = trigger_rag_sync(
        db, property_id=property_id, source="reviews", reason="review_import"
    )
    summary["provider"] = provider
    summary["sync_job_id"] = job.id
    if settings.rag_autosync and background is not None:
        background.add_task(drain_queue)
    return summary


@router.put("/{property_id}/{review_id}", response_model=ReviewOut)
def update_review(
    property_id: int, review_id: int, payload: ReviewIn, db: Session = Depends(get_db)
):
    review = (
        db.query(PropertyReview)
        .filter_by(id=review_id, property_id=property_id)
        .one_or_none()
    )
    if review is None:
        raise HTTPException(status_code=404, detail="Review not found.")
    for field, value in payload.model_dump().items():
        setattr(review, field, value)
    review.updated_at = datetime.now(timezone.utc)
    db.commit()
    db.refresh(review)
    trigger_rag_sync(db, property_id=property_id, source="reviews", reason="review_update")
    return review


@router.delete("/{property_id}/{review_id}", status_code=200)
def delete_review(property_id: int, review_id: int, db: Session = Depends(get_db)):
    review = (
        db.query(PropertyReview)
        .filter_by(id=review_id, property_id=property_id)
        .one_or_none()
    )
    if review is None:
        raise HTTPException(status_code=404, detail="Review not found.")
    db.delete(review)
    db.commit()
    # Refresh review chunks so the deleted review's chunk is removed and Nora
    # can no longer cite it.
    job = trigger_rag_sync(db, property_id=property_id, source="reviews", reason="review_delete")
    return {"status": "deleted", "review_id": review_id, "sync_job_id": job.id}
