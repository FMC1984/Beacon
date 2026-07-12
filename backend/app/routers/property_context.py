"""Property context CRUD. Values are validated against the JSON vocabulary;
writing enqueues the existing RAG sync so the property_context chunk (and the
Content Intelligence chunk that references it) refresh. Operator-asserted only:
this endpoint is the only way regulatory/program/type status is ever set."""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.db import get_db
from app.extensions.hooks import trigger_rag_sync
from app.models import Property, PropertyProfile
from app.services.property_context import (
    ContextValidationError,
    config,
    get_property_context,
    validate_assignment,
)

router = APIRouter(prefix="/property-context", tags=["property-context"])


class PropertyContextIn(BaseModel):
    property_type: str | None = None
    target_audience: str | None = None
    # Three-state: True regulated, False not regulated, None unspecified (UNKNOWN).
    is_regulated: bool | None = None
    regulatory_programs: list[str] = []
    marketing_restriction_flags: list[str] = []
    marketing_restriction_notes: str | None = None


@router.get("/vocabulary")
def vocabulary():
    c = config()
    return {
        "property_types": c["property_types"],
        "regulatory_programs": c["regulatory_programs"],
        "restriction_flags": c["restriction_flags"],
    }


@router.get("/{property_id}")
def read_context(property_id: int, db: Session = Depends(get_db)):
    if db.get(Property, property_id) is None:
        raise HTTPException(status_code=404, detail="Property not found.")
    return get_property_context(db, property_id)


@router.put("/{property_id}")
def upsert_context(
    property_id: int, payload: PropertyContextIn, db: Session = Depends(get_db)
):
    if db.get(Property, property_id) is None:
        raise HTTPException(status_code=404, detail="Property not found.")
    try:
        validate_assignment(
            payload.property_type,
            payload.regulatory_programs,
            payload.marketing_restriction_flags,
        )
    except ContextValidationError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    row = (
        db.query(PropertyProfile).filter_by(property_id=property_id).one_or_none()
    )
    if row is None:
        row = PropertyProfile(property_id=property_id)
        db.add(row)
    row.property_type = payload.property_type
    row.target_audience = payload.target_audience
    row.is_regulated = payload.is_regulated
    row.regulatory_programs = payload.regulatory_programs
    row.marketing_restriction_flags = payload.marketing_restriction_flags
    row.marketing_restriction_notes = payload.marketing_restriction_notes
    row.updated_at = datetime.now(timezone.utc)
    db.commit()

    trigger_rag_sync(
        db, property_id=property_id, source="property_context", reason="context_edit"
    )
    return get_property_context(db, property_id)
