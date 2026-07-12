import re
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.config import settings
from app.db import get_db
from app.models import (
    Company,
    CRMLead,
    GA4SessionsDaily,
    GBPMetricsDaily,
    GSCPerformanceDaily,
    NoraConversation,
    NoraMessage,
    PaidMediaDaily,
    Property,
    PropertyContent,
    PropertyProfile,
    PropertyReview,
    RAGChunk,
    RagSyncJob,
    Report,
    Upload,
)
from app.schemas.properties import PropertyCreate, PropertyOut, PropertyUpdate
from app.services.property_types import (
    InvalidPropertyTypeError,
    config as property_type_config,
    validate_property_type,
)
from app.services.rag.store import get_collection

router = APIRouter(prefix="/properties", tags=["properties"])


def slugify(name: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")
    if not slug:
        raise HTTPException(status_code=422, detail="Name produces an empty slug.")
    return slug


def _require_company(db: Session, company_id: int | None) -> None:
    if company_id is not None and db.get(Company, company_id) is None:
        raise HTTPException(status_code=422, detail="Company not found.")


def _valid_type(value: str | None) -> str:
    try:
        return validate_property_type(value)
    except InvalidPropertyTypeError as exc:
        raise HTTPException(status_code=422, detail=str(exc))


@router.get("/types/config")
def property_types():
    """Client/site type vocabulary + per-type config (terminology, allowed
    connectors, KB selection). The frontend uses this to relabel and to filter
    connectors."""
    return property_type_config()


@router.post("", response_model=PropertyOut, status_code=201)
def create_property(payload: PropertyCreate, db: Session = Depends(get_db)):
    slug = payload.slug or slugify(payload.name)
    exists = (
        db.query(Property)
        .filter((Property.name == payload.name) | (Property.slug == slug))
        .first()
    )
    if exists:
        raise HTTPException(
            status_code=409, detail="A property with that name or slug already exists."
        )
    _require_company(db, payload.company_id)
    prop = Property(
        name=payload.name,
        slug=slug,
        property_type=_valid_type(payload.property_type),
        company_id=payload.company_id,
        external_code=payload.external_code,
        city=payload.city,
        state=payload.state,
        unit_count=payload.unit_count,
        website_url=payload.website_url,
    )
    db.add(prop)
    db.commit()
    db.refresh(prop)
    return prop


@router.get("", response_model=list[PropertyOut])
def list_properties(db: Session = Depends(get_db)):
    return db.query(Property).order_by(Property.name).all()


@router.get("/{property_id}", response_model=PropertyOut)
def get_property(property_id: int, db: Session = Depends(get_db)):
    prop = db.get(Property, property_id)
    if prop is None:
        raise HTTPException(status_code=404, detail="Property not found.")
    return prop


@router.patch("/{property_id}", response_model=PropertyOut)
def update_property(
    property_id: int, payload: PropertyUpdate, db: Session = Depends(get_db)
):
    prop = db.get(Property, property_id)
    if prop is None:
        raise HTTPException(status_code=404, detail="Property not found.")
    changes = payload.model_dump(exclude_unset=True)
    if "company_id" in changes:
        _require_company(db, changes["company_id"])
    if "property_type" in changes:
        changes["property_type"] = _valid_type(changes["property_type"])
    for field, value in changes.items():
        setattr(prop, field, value)
    db.commit()
    db.refresh(prop)
    return prop


@router.delete("/{property_id}", status_code=200)
def delete_property(property_id: int, db: Session = Depends(get_db)):
    """Cascading delete: every row scoped to this property, its uploaded files,
    and its RAG vectors. Irreversible; intended for clearing test/demo data."""
    prop = db.get(Property, property_id)
    if prop is None:
        raise HTTPException(status_code=404, detail="Property not found.")

    # Remove vectors for this property's chunks before deleting the registry rows.
    chunk_ids = [
        c.chroma_id
        for c in db.query(RAGChunk).filter_by(property_id=property_id).all()
    ]
    if chunk_ids:
        try:
            get_collection().delete(ids=chunk_ids)
        except Exception:
            pass  # collection may not exist yet; registry cleanup still proceeds

    # Delete raw uploaded files from disk before removing the Upload rows.
    uploads = db.query(Upload).filter_by(property_id=property_id).all()
    for u in uploads:
        if u.stored_path:
            Path(u.stored_path).unlink(missing_ok=True)

    # Child tables first (FK order), then uploads, then the property itself.
    for model in (
        GA4SessionsDaily,
        GSCPerformanceDaily,
        GBPMetricsDaily,
        PaidMediaDaily,
        CRMLead,
        PropertyReview,
        PropertyContent,
        RAGChunk,
        RagSyncJob,
        Report,
    ):
        db.query(model).filter_by(property_id=property_id).delete()

    db.query(PropertyProfile).filter_by(property_id=property_id).delete()

    convo_ids = [
        c.id
        for c in db.query(NoraConversation).filter_by(property_id=property_id).all()
    ]
    if convo_ids:
        db.query(NoraMessage).filter(
            NoraMessage.conversation_id.in_(convo_ids)
        ).delete(synchronize_session=False)
        db.query(NoraConversation).filter_by(property_id=property_id).delete()

    db.query(Upload).filter_by(property_id=property_id).delete()
    db.delete(prop)
    db.commit()
    return {"status": "deleted", "property_id": property_id}
