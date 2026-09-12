"""Entity terms and mention detection for shared market scoring (Phase 19,
slice 3). A market run has no owning property, so the entity list is every
eligible property in the market plus each property's tracked competitors.
Detection reuses parsing.find_mention (the same deterministic whole-word
matching brand detection has always used); a short or generic name gets a
lower confidence so a coincidental word never becomes a strong mention."""

from dataclasses import dataclass

from sqlalchemy.orm import Session

from app.models import (
    ENTITY_COMPETITOR,
    ENTITY_PROPERTY,
    AIRun,
    AIVisibilityQuery,
    Competitor,
    Mention,
    Property,
)
from app.services.ai_visibility.mentions import resolve_competitor_terms, resolve_property_terms
from app.services.ai_visibility.parsing import find_mention

# Names this short read as ordinary words too often to count at full confidence.
_LOW_CONFIDENCE_MAX_CHARS = 4
_LOW_CONFIDENCE = 0.5


@dataclass(frozen=True)
class EntityTerm:
    entity_type: str
    entity_id: int
    name: str
    terms: tuple[str, ...]
    # For competitors: the property that tracks them (competitors are per-property).
    owner_property_id: int | None = None
    domain: str | None = None


@dataclass
class MentionDraft:
    entity_type: str
    entity_id: int
    normalized_name: str
    raw_matched_text: str
    match_count: int
    position: int
    confidence: float
    owner_property_id: int | None = None


def entities_for_properties(db: Session, properties: list[Property]) -> list[EntityTerm]:
    """Property terms + each property's competitor terms, de-duplicated per
    (type, id)."""
    entities: list[EntityTerm] = []
    seen: set[tuple[str, int]] = set()
    for prop in properties:
        key = (ENTITY_PROPERTY, prop.id)
        if key not in seen:
            seen.add(key)
            entities.append(EntityTerm(
                entity_type=ENTITY_PROPERTY, entity_id=prop.id, name=prop.name,
                terms=tuple(resolve_property_terms(prop)), domain=prop.domain,
            ))
    prop_ids = [p.id for p in properties]
    if prop_ids:
        for comp in db.query(Competitor).filter(Competitor.property_id.in_(prop_ids)).all():
            key = (ENTITY_COMPETITOR, comp.id)
            if key in seen:
                continue
            seen.add(key)
            entities.append(EntityTerm(
                entity_type=ENTITY_COMPETITOR, entity_id=comp.id, name=comp.name,
                terms=tuple(resolve_competitor_terms(comp)), owner_property_id=comp.property_id,
                domain=comp.domain,
            ))
    return entities


def detect_entity_mentions(text: str, entities: list[EntityTerm]) -> list[MentionDraft]:
    drafts: list[MentionDraft] = []
    for e in entities:
        hit = find_mention(text or "", list(e.terms))
        if not hit:
            continue
        confidence = _LOW_CONFIDENCE if len(hit["term"].strip()) <= _LOW_CONFIDENCE_MAX_CHARS else 1.0
        drafts.append(MentionDraft(
            entity_type=e.entity_type, entity_id=e.entity_id, normalized_name=e.name,
            raw_matched_text=hit["term"], match_count=hit["count"], position=hit["position"],
            confidence=confidence, owner_property_id=e.owner_property_id,
        ))
    drafts.sort(key=lambda d: d.position)
    return drafts


def persist_entity_mentions(
    db: Session, response: AIVisibilityQuery, run: AIRun | None, drafts: list[MentionDraft]
) -> list[Mention]:
    """Idempotent replacement of the response's Mention rows (all entities)."""
    db.query(Mention).filter_by(response_id=response.id).delete()
    rows: list[Mention] = []
    for d in drafts:
        row = Mention(
            response_id=response.id, run_id=run.id if run else None,
            entity_type=d.entity_type, entity_id=d.entity_id,
            normalized_name=d.normalized_name, raw_matched_text=d.raw_matched_text,
            match_count=d.match_count, position=d.position, confidence=d.confidence,
            mention_type="named",
        )
        db.add(row)
        rows.append(row)
    db.flush()
    return rows
