"""Competitor CRUD (Phase 13). Competitors are operator-asserted, never
inferred. Any change enqueues a RAG sync (source "competitors"), which refreshes
the derived Competitor Intelligence share-of-voice chunk."""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.db import get_db
from app.extensions.hooks import trigger_rag_sync
from app.models import Competitor, Property
from app.schemas.competitors import CompetitorIn, CompetitorOut

router = APIRouter(prefix="/competitors", tags=["competitors"])


def _require_property(db: Session, property_id: int):
    if db.get(Property, property_id) is None:
        raise HTTPException(status_code=404, detail="Property not found.")


def _clean(payload: CompetitorIn) -> dict:
    name = payload.name.strip()
    if not name:
        raise HTTPException(status_code=422, detail="Competitor name is required.")
    aliases = [a.strip() for a in (payload.aliases or []) if a.strip()]
    return {"name": name, "aliases": aliases, "domain": (payload.domain or "").strip() or None}


@router.get("/{property_id}", response_model=list[CompetitorOut])
def list_competitors(property_id: int, db: Session = Depends(get_db)):
    _require_property(db, property_id)
    return (
        db.query(Competitor)
        .filter_by(property_id=property_id)
        .order_by(Competitor.name)
        .all()
    )


@router.post("/{property_id}", response_model=CompetitorOut, status_code=201)
def create_competitor(property_id: int, payload: CompetitorIn, db: Session = Depends(get_db)):
    _require_property(db, property_id)
    row = Competitor(property_id=property_id, **_clean(payload))
    db.add(row)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(
            status_code=409, detail="A competitor with that name already exists for this property."
        )
    db.refresh(row)
    trigger_rag_sync(db, property_id=property_id, source="competitors", reason="competitor_create")
    return row


@router.put("/{property_id}/{competitor_id}", response_model=CompetitorOut)
def update_competitor(
    property_id: int, competitor_id: int, payload: CompetitorIn, db: Session = Depends(get_db)
):
    row = (
        db.query(Competitor)
        .filter_by(id=competitor_id, property_id=property_id)
        .one_or_none()
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Competitor not found.")
    clean = _clean(payload)
    row.name = clean["name"]
    row.aliases = clean["aliases"]
    row.domain = clean["domain"]
    row.updated_at = datetime.now(timezone.utc)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        raise HTTPException(status_code=409, detail="A competitor with that name already exists.")
    db.refresh(row)
    trigger_rag_sync(db, property_id=property_id, source="competitors", reason="competitor_update")
    return row


@router.delete("/{property_id}/{competitor_id}", status_code=200)
def delete_competitor(property_id: int, competitor_id: int, db: Session = Depends(get_db)):
    row = (
        db.query(Competitor)
        .filter_by(id=competitor_id, property_id=property_id)
        .one_or_none()
    )
    if row is None:
        raise HTTPException(status_code=404, detail="Competitor not found.")
    db.delete(row)
    db.commit()
    job = trigger_rag_sync(db, property_id=property_id, source="competitors", reason="competitor_delete")
    return {"status": "deleted", "competitor_id": competitor_id, "sync_job_id": job.id}
