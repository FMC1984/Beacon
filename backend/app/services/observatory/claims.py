"""AI fact accuracy (Phase 19, slice 5).

Deterministic claim extraction from the sentences of a stored AI answer that
name the property, verified against facts Beacon already holds:

  property_type  Property Context type (the Phase 11.5 synonym vocabulary)
  state          the property's state (full state names only)
  pets           Property.attributes["pet_policy"]
  amenity        Property.attributes["amenities"], then site content topics
  rent           Property.attributes["rent_range"] = {"min": n, "max": n}

Statuses: confirmed (matches a fact Beacon holds), likely_accurate
(consistent with softer evidence: site content, or a rent inside a stated
range that can drift), conflict_detected (contradicts a fact Beacon holds,
evidence stated), unable_to_verify (no reliable fact to compare). Beacon
never marks a claim false without a stored fact that contradicts it; the
absence of an amenity from a list is NOT evidence it does not exist.
"""

import hashlib
import re
from dataclasses import dataclass
from datetime import datetime

from sqlalchemy.orm import Session

from app.models import AIClaim, AIVisibilityQuery, Property, PropertyContent
from app.models.ai_intelligence import (
    CLAIM_CONFIRMED,
    CLAIM_CONFLICT,
    CLAIM_LIKELY_ACCURATE,
    CLAIM_UNVERIFIABLE,
)
from app.services.ai_visibility.hallucination import _STATES
from app.services.ai_visibility.mentions import resolve_property_terms
from app.services.ai_visibility.parsing import _phrase_present, find_mention
from app.services.ai_visibility.reference import config as visibility_config
from app.services.property_context import get_property_context
from app.services.semantic import match_with_negation
from app.services.jobs.queue import utcnow

RESPONSE_IDS_KEEP = 20

AMENITY_TERMS = {
    "pool": ["pool", "swimming pool"],
    "fitness_center": ["fitness center", "gym", "fitness room"],
    "garage": ["garage", "garages"],
    "ev_charging": ["ev charging", "electric vehicle charging", "ev chargers"],
    "washer_dryer": ["washer and dryer", "in-unit laundry", "washer/dryer", "in-home washer"],
    "dog_park": ["dog park", "bark park", "pet park"],
    "clubhouse": ["clubhouse"],
}
PETS_YES = ["pet friendly", "pet-friendly", "pets allowed", "dog friendly", "dog-friendly", "allows pets", "welcomes pets", "cat friendly"]
PETS_NO = ["no pets", "not pet friendly", "not pet-friendly", "pets are not allowed", "does not allow pets", "doesn't allow pets", "pet-free"]
PET_ALLOWED_VALUES = {"allowed", "pet_friendly", "pet friendly", "yes", "true", "restricted", "cats_only", "dogs_and_cats"}
PET_NOT_ALLOWED_VALUES = {"not_allowed", "no_pets", "no", "false", "none"}
RENT_RE = re.compile(r"\$\s?(\d{1,2},?\d{3})(?:\s?(?:-|to)\s?\$?\s?(\d{1,2},?\d{3}))?")
_SENTENCE_SPLIT = re.compile(r"(?<=[.!?])\s+|\n+")

SEVERITY_CONFLICT = {"property_type": "high", "pets": "high", "state": "high", "rent": "medium", "amenity": "medium"}


@dataclass
class ClaimDraft:
    claim_type: str
    topic: str | None
    value: str
    text: str
    status: str
    method: str
    evidence: str
    known_value: str | None = None


def mention_sentences(text: str, terms: list[str]) -> list[str]:
    return [s.strip() for s in _SENTENCE_SPLIT.split(text or "") if s.strip() and find_mention(s, terms)]


def _norm_list(values) -> list[str]:
    if isinstance(values, str):
        values = [values]
    return [str(v).lower().replace("-", " ").replace("_", " ") for v in (values or [])]


def _type_claims(sentence: str, ctx: dict) -> list[ClaimDraft]:
    synonyms: dict = visibility_config().get("property_type_synonyms", {})
    first_term: dict[str, str] = {}
    for t, terms in synonyms.items():
        for term in terms + [t]:
            if _phrase_present(sentence, term):
                first_term.setdefault(t, term)
    if not first_term:
        return []
    known = ctx.get("property_type")
    out = []
    for ptype, term in first_term.items():
        if not known:
            status, evidence = CLAIM_UNVERIFIABLE, "Property Context does not set a property type."
        elif ptype == known:
            status, evidence = CLAIM_CONFIRMED, f"Matches the Property Context type '{known}'."
        else:
            status, evidence = CLAIM_CONFLICT, f"Describes the property as '{term}' ({ptype}); Property Context sets '{known}'."
        out.append(ClaimDraft("property_type", ptype, ptype, sentence, status, "property_context_type", evidence, known))
    return out


def _state_claims(sentence: str, prop: Property) -> list[ClaimDraft]:
    lowered = sentence.lower()
    named = [name for name in _STATES if re.search(rf"\b{re.escape(name)}\b", lowered)]
    if not named or not prop.state:
        return []
    known = prop.state.strip().upper()
    out = []
    for name in named:
        abbr = _STATES[name]
        if abbr == known:
            out.append(ClaimDraft("state", None, abbr, sentence, CLAIM_CONFIRMED, "property_record_state",
                                  f"Matches the property's state ({known}).", known))
        elif not any(_STATES[n] == known for n in named):
            out.append(ClaimDraft("state", None, abbr, sentence, CLAIM_CONFLICT, "property_record_state",
                                  f"Places the property in {name.title()}; the property record says {known}.", known))
    return out


def _pet_claims(sentence: str, attrs: dict) -> list[ClaimDraft]:
    yes = match_with_negation(sentence, PETS_YES, positive=True)
    no = match_with_negation(sentence, PETS_NO)
    says_yes = bool(yes.clean)
    says_no = bool(no.clean or yes.flipped)
    if not (says_yes or says_no) or (says_yes and says_no):
        return []
    policy = str(attrs.get("pet_policy") or "").strip().lower()
    value = "pets allowed" if says_yes else "no pets"
    if not policy:
        return [ClaimDraft("pets", "pets", value, sentence, CLAIM_UNVERIFIABLE, "attributes_pet_policy",
                           "No pet policy is recorded for the property.")]
    allowed = policy in PET_ALLOWED_VALUES
    blocked = policy in PET_NOT_ALLOWED_VALUES
    if not (allowed or blocked):
        return [ClaimDraft("pets", "pets", value, sentence, CLAIM_UNVERIFIABLE, "attributes_pet_policy",
                           f"Recorded pet policy '{policy}' cannot be compared.", policy)]
    match = allowed if says_yes else blocked
    return [ClaimDraft(
        "pets", "pets", value, sentence, CLAIM_CONFIRMED if match else CLAIM_CONFLICT, "attributes_pet_policy",
        f"Recorded pet policy is '{policy}'." if match else f"Says '{value}', but the recorded pet policy is '{policy}'.",
        policy,
    )]


def _amenity_claims(sentence: str, attrs: dict, content_topics: set[str]) -> list[ClaimDraft]:
    recorded = _norm_list(attrs.get("amenities"))
    out = []
    for topic, terms in AMENITY_TERMS.items():
        res = match_with_negation(sentence, terms, positive=True)
        negated = bool(res.flipped or res.excluded) and not res.clean
        if not (res.clean or negated):
            continue
        listed = any(any(t in r or r in t for t in [topic.replace("_", " ")] + terms) for r in recorded)
        label = topic.replace("_", " ")
        if negated:
            if listed:
                out.append(ClaimDraft("amenity", topic, f"no {label}", sentence, CLAIM_CONFLICT, "attributes_amenities",
                                      f"Says the property has no {label}; the recorded amenities include it."))
            else:
                out.append(ClaimDraft("amenity", topic, f"no {label}", sentence, CLAIM_UNVERIFIABLE, "attributes_amenities",
                                      "Beacon has no record that confirms or rules out this amenity."))
            continue
        if listed:
            out.append(ClaimDraft("amenity", topic, f"has {label}", sentence, CLAIM_CONFIRMED, "attributes_amenities",
                                  "Listed in the recorded amenities."))
        elif topic in content_topics:
            out.append(ClaimDraft("amenity", topic, f"has {label}", sentence, CLAIM_LIKELY_ACCURATE, "site_content_topics",
                                  "The property's own site content covers this amenity."))
        else:
            out.append(ClaimDraft("amenity", topic, f"has {label}", sentence, CLAIM_UNVERIFIABLE, "attributes_amenities",
                                  "Not in the recorded amenities or site content; not treated as false."))
    return out


def _money(s: str) -> int:
    return int(s.replace(",", ""))


def _rent_claims(sentence: str, attrs: dict) -> list[ClaimDraft]:
    m = RENT_RE.search(sentence)
    if not m:
        return []
    lo = _money(m.group(1))
    hi = _money(m.group(2)) if m.group(2) else lo
    value = f"${lo:,}" if lo == hi else f"${lo:,} to ${hi:,}"
    rr = attrs.get("rent_range") or {}
    try:
        rmin, rmax = float(rr.get("min")), float(rr.get("max"))
    except (TypeError, ValueError):
        return [ClaimDraft("rent", "rent", value, sentence, CLAIM_UNVERIFIABLE, "attributes_rent_range",
                           "No rent range is recorded for the property.")]
    known = f"${int(rmin):,} to ${int(rmax):,}"
    if lo >= rmin * 0.9 and hi <= rmax * 1.1:
        return [ClaimDraft("rent", "rent", value, sentence, CLAIM_LIKELY_ACCURATE, "attributes_rent_range",
                           f"Within the recorded range {known} (rents change, so not confirmed).", known)]
    if hi < rmin * 0.75 or lo > rmax * 1.25:
        return [ClaimDraft("rent", "rent", value, sentence, CLAIM_CONFLICT, "attributes_rent_range",
                           f"More than 25% outside the recorded range {known}.", known)]
    return [ClaimDraft("rent", "rent", value, sentence, CLAIM_UNVERIFIABLE, "attributes_rent_range",
                       f"Near but outside the recorded range {known}; may reflect a price change.", known)]


def extract_claims(text: str, prop: Property, ctx: dict, content_topics: set[str]) -> list[ClaimDraft]:
    attrs = prop.attributes or {}
    drafts: list[ClaimDraft] = []
    for sentence in mention_sentences(text, resolve_property_terms(prop)):
        drafts += _type_claims(sentence, ctx)
        drafts += _state_claims(sentence, prop)
        drafts += _pet_claims(sentence, attrs)
        drafts += _amenity_claims(sentence, attrs, content_topics)
        drafts += _rent_claims(sentence, attrs)
    unique: dict[tuple, ClaimDraft] = {}
    for d in drafts:
        unique.setdefault((d.claim_type, d.topic, d.value), d)
    return list(unique.values())


def claim_hash(d: ClaimDraft) -> str:
    return hashlib.sha256(f"{d.claim_type}|{d.topic or ''}|{d.value.lower()}".encode()).hexdigest()


def _content_topics(db: Session, property_id: int) -> set[str]:
    topics: set[str] = set()
    for (t,) in db.query(PropertyContent.topics).filter_by(property_id=property_id).all():
        topics.update(t or [])
    return topics


def persist_claims_for_response(db: Session, response: AIVisibilityQuery, property_ids: list[int]) -> list[AIClaim]:
    """Upsert the claims this answer makes about each property. Idempotent per
    response; verification is recomputed from current facts every time."""
    rows: list[AIClaim] = []
    seen_at = response.executed_at or utcnow()
    for pid in property_ids:
        prop = db.get(Property, pid)
        if prop is None:
            continue
        ctx = get_property_context(db, pid)
        for d in extract_claims(response.raw_response_text or "", prop, ctx, _content_topics(db, pid)):
            h = claim_hash(d)
            row = db.query(AIClaim).filter_by(property_id=pid, claim_hash=h).one_or_none()
            if row is None:
                row = AIClaim(
                    organization_id=response.organization_id, property_id=pid, claim_type=d.claim_type,
                    claim_topic=d.topic, claim_value=d.value, claim_text=d.text[:2000], claim_hash=h,
                    first_seen=seen_at, last_seen=seen_at, occurrence_count=0, response_ids=[], platforms=[],
                    verification_status=d.status, verification_method=d.method, evidence=d.evidence,
                )
                db.add(row)
            ids = list(row.response_ids or [])
            if response.id not in ids:
                ids.append(response.id)
                row.occurrence_count = (row.occurrence_count or 0) + 1
                row.last_seen = max(row.last_seen or seen_at, seen_at)
                row.claim_text = d.text[:2000]
            row.response_ids = ids[-RESPONSE_IDS_KEEP:]
            row.platforms = sorted(set((row.platforms or []) + [response.platform]))
            row.verification_status = d.status
            row.verification_method = d.method
            row.evidence = d.evidence
            row.known_value = d.known_value
            row.severity = SEVERITY_CONFLICT.get(d.claim_type, "low") if d.status == CLAIM_CONFLICT else "low"
            row.updated_at = utcnow()
            rows.append(row)
    db.flush()
    return rows


def backfill_claims(db: Session, property_id: int) -> dict:
    from app.models import AIPropertyObservation

    response_ids = [
        rid for (rid,) in db.query(AIPropertyObservation.response_id)
        .filter(AIPropertyObservation.property_id == property_id, AIPropertyObservation.mentioned.is_(True))
        .order_by(AIPropertyObservation.response_id)
        .all()
    ]
    for rid in response_ids:
        persist_claims_for_response(db, db.get(AIVisibilityQuery, rid), [property_id])
    db.commit()
    return {"property_id": property_id, "responses_scanned": len(response_ids),
            "claims": db.query(AIClaim).filter_by(property_id=property_id).count()}
