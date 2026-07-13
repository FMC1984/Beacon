"""Content change log CRUD (Phase 16F). Operator-recorded website changes that
the Content Impact report reads to show performance around a change date.
Recording a change never asserts causation."""

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import get_db
from app.models import ContentChange, Property
from app.schemas.content_changes import ContentChangeIn, ContentChangeOut

router = APIRouter(prefix="/content-changes", tags=["content-changes"])


def _require_property(db: Session, property_id: int) -> Property:
    prop = db.get(Property, property_id)
    if prop is None:
        raise HTTPException(status_code=404, detail="Property not found.")
    return prop


def _clean(payload: ContentChangeIn) -> dict:
    title = payload.change_title.strip()
    if not title:
        raise HTTPException(status_code=422, detail="Change title is required.")
    data = payload.model_dump()
    data["change_title"] = title
    for k in ("page_url", "notes", "related_opportunity", "created_by",
              "before_snapshot_ref", "after_snapshot_ref"):
        v = data.get(k)
        data[k] = v.strip() if isinstance(v, str) and v.strip() else None
    return data


@router.get("/{property_id}", response_model=list[ContentChangeOut])
def list_changes(property_id: int, db: Session = Depends(get_db)):
    _require_property(db, property_id)
    return (
        db.query(ContentChange)
        .filter_by(property_id=property_id)
        .order_by(ContentChange.date_implemented.desc(), ContentChange.id.desc())
        .all()
    )


@router.post("/{property_id}", response_model=ContentChangeOut, status_code=201)
def create_change(property_id: int, payload: ContentChangeIn, db: Session = Depends(get_db)):
    prop = _require_property(db, property_id)
    row = ContentChange(property_id=property_id, company_id=prop.company_id, **_clean(payload))
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


@router.put("/{property_id}/{change_id}", response_model=ContentChangeOut)
def update_change(property_id: int, change_id: int, payload: ContentChangeIn, db: Session = Depends(get_db)):
    _require_property(db, property_id)
    row = db.get(ContentChange, change_id)
    if row is None or row.property_id != property_id:
        raise HTTPException(status_code=404, detail="Change not found.")
    for k, v in _clean(payload).items():
        setattr(row, k, v)
    db.commit()
    db.refresh(row)
    return row


@router.delete("/{property_id}/{change_id}")
def delete_change(property_id: int, change_id: int, db: Session = Depends(get_db)):
    _require_property(db, property_id)
    row = db.get(ContentChange, change_id)
    if row is None or row.property_id != property_id:
        raise HTTPException(status_code=404, detail="Change not found.")
    db.delete(row)
    db.commit()
    return {"status": "deleted", "change_id": change_id}
