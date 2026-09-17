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
from app.services.setup import property_setup

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
        address_line1=payload.address_line1,
        zip=payload.zip,
        lat=payload.lat,
        lng=payload.lng,
        submarket_id=payload.submarket_id,
        attributes=payload.attributes,
        management_company=payload.management_company,
        ownership=payload.ownership,
        known_competitor_domains=payload.known_competitor_domains,
    )
    _derive_observatory_fields(db, prop)
    db.add(prop)
    db.commit()
    db.refresh(prop)
    return prop


def _derive_observatory_fields(db: Session, prop: Property) -> None:
    """Phase 19: market from city/state, owned domain from website_url.
    Derived, never operator-entered, so they stay consistent with the
    fields they come from."""
    from app.services.observatory.citations import domain_of_url
    from app.services.observatory.markets import assign_property_market, assign_property_submarket

    assign_property_market(db, prop)
    assign_property_submarket(db, prop)
    prop.domain = domain_of_url(prop.website_url)


@router.get("", response_model=list[PropertyOut])
def list_properties(db: Session = Depends(get_db)):
    return db.query(Property).order_by(Property.name).all()


@router.get("/{property_id}", response_model=PropertyOut)
def get_property(property_id: int, db: Session = Depends(get_db)):
    prop = db.get(Property, property_id)
    if prop is None:
        raise HTTPException(status_code=404, detail="Property not found.")
    return prop


@router.get("/{property_id}/setup")
def get_property_setup(property_id: int, db: Session = Depends(get_db)):
    """Setup checklist: six dependency-ordered steps, each a deterministic
    check over existing rows, with what it unlocks and where to do it."""
    if db.get(Property, property_id) is None:
        raise HTTPException(status_code=404, detail="Property not found.")
    return property_setup(db, property_id)


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
    if "attributes" in changes:
        # Merge, never replace: a form that edits one attribute (say the
        # neighborhood) must not wipe amenities, pet policy or the sample flag.
        merged = dict(prop.attributes or {})
        for k, v in (changes["attributes"] or {}).items():
            if v is None:
                merged.pop(k, None)
            else:
                merged[k] = v
        changes["attributes"] = merged
    for field, value in changes.items():
        setattr(prop, field, value)
    if changes.keys() & {"city", "state", "website_url", "attributes"}:
        _derive_observatory_fields(db, prop)
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

    # AI Visibility / Observatory family (Phase 18-19), leaf rows first.
    from app.models import (
        ENTITY_COMPETITOR,
        ENTITY_PROPERTY,
        AIBudget,
        AICitation,
        AIClaim,
        AIClusterVisibilityDaily,
        AIContentGap,
        AIEntityDecision,
        AIRunSchedule,
        AISourceDomainRollup,
        AICompetitorStat,
        PropertyFact,
        AIVisibilityAlert,
        AIPromptAssignment,
        AIPromptCluster,
        AIPromptEmbedding,
        AIPropertyObservation,
        AIRun,
        AISearchQuery,
        AIShareOfVoiceSnapshot,
        AITopic,
        AIVisibilityPrompt,
        AIVisibilityQuery,
        AIVisibilityDaily,
        AIVisibilityScoreHistory,
        Competitor,
        Mention,
    )

    # Derived rows and rollups first (they reference responses and the property).
    for model in (
        AIPropertyObservation, AIVisibilityDaily, AIClusterVisibilityDaily, AIPromptAssignment,
        AIClaim, AIEntityDecision, AIVisibilityAlert, AIRunSchedule, AIContentGap,
        AISourceDomainRollup, AICompetitorStat, PropertyFact,
    ):
        db.query(model).filter_by(property_id=property_id).delete(synchronize_session=False)
    # This property's entities inside shared market answers.
    competitor_ids = [cid for (cid,) in db.query(Competitor.id).filter_by(property_id=property_id)]
    db.query(Mention).filter(Mention.entity_type == ENTITY_PROPERTY, Mention.entity_id == property_id).delete(
        synchronize_session=False)
    if competitor_ids:
        db.query(Mention).filter(
            Mention.entity_type == ENTITY_COMPETITOR, Mention.entity_id.in_(competitor_ids)
        ).delete(synchronize_session=False)
    prompt_ids = [pid for (pid,) in db.query(AIVisibilityPrompt.id).filter_by(property_id=property_id)]
    if prompt_ids:
        db.query(AIPromptEmbedding).filter(AIPromptEmbedding.prompt_id.in_(prompt_ids)).delete(
            synchronize_session=False)
        db.query(AIRunSchedule).filter(AIRunSchedule.prompt_id.in_(prompt_ids)).delete(synchronize_session=False)
    db.query(AIPromptCluster).filter_by(property_id=property_id).delete(synchronize_session=False)

    response_ids = [
        rid for (rid,) in db.query(AIVisibilityQuery.id).filter_by(property_id=property_id)
    ]
    if response_ids:
        for leaf in (AIPropertyObservation, Mention, AICitation, AISearchQuery):
            db.query(leaf).filter(leaf.response_id.in_(response_ids)).delete(
                synchronize_session=False
            )
    for model in (
        AIVisibilityQuery,
        AIRun,
        AIShareOfVoiceSnapshot,
        AIVisibilityPrompt,
        AITopic,
        AIVisibilityScoreHistory,
        Competitor,
    ):
        db.query(model).filter_by(property_id=property_id).delete()
    db.query(AIBudget).filter_by(scope_type="property", scope_id=property_id).delete()

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
