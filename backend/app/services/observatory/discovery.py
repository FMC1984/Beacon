"""AI-discovered competitor candidates (Phase 19, slice 5).

Deterministic extraction of apartment-community names from stored AI answers
in a market: Title Case phrases that end in a multifamily naming suffix
("Flats", "Apartments", "Commons", "at <Place>"...) or that an answer sets in
bold as a list item. Names Beacon already knows (the market's properties,
their aliases and tracked competitors) are excluded, as are directories,
brands with a domain in them and generic phrases ("Luxury Apartments").

A candidate is only a candidate. Competitors stay operator-named: a name
becomes a Competitor row for a property only when someone confirms it
(AIEntityDecision). Confidence is MODELED from how many distinct answers
named it.
"""

import re
from datetime import datetime

from sqlalchemy import or_
from sqlalchemy.orm import Session

from app.models import (
    AIDiscoveredEntity,
    AIEntityDecision,
    AIVisibilityQuery,
    Competitor,
    Property,
)
from app.models.ai_intelligence import DECISION_CONFIRMED, DECISION_IGNORED
from app.services.ai_visibility.mentions import resolve_competitor_terms, resolve_property_terms
from app.services.observatory import LABEL_MODELED
from app.services.observatory.markets import market_members
from app.services.jobs.queue import utcnow

SUFFIXES = (
    "Apartments", "Apartment Homes", "Apartment Community", "Flats", "Lofts", "Commons",
    "Residences", "Village", "Villas", "Place", "Station", "Crossing", "Townhomes",
    "Park", "Ridge", "Pointe", "Point", "Landing", "Gardens", "Heights", "Square",
    "Terrace", "Court", "Towers", "Tower", "Lodge", "Row", "Yards", "Reserve", "Estates",
    "Meadows", "Springs", "Vista", "Summit", "Grove", "Hills", "Creek", "Trails", "Club",
)
# Leading words that make a phrase a category, not a community name.
GENERIC_LEADS = {
    "best", "top", "luxury", "affordable", "cheap", "new", "senior", "student", "pet",
    "family", "downtown", "nearby", "local", "popular", "modern", "several", "many", "other",
    "these", "those", "some", "all", "most", "low", "income", "section", "public", "rental",
    "studio", "one", "two", "three", "furnished", "gated", "garden", "high", "mid",
}
# Sentence words that precede a name without being part of it ("Try Solana at RidgeGate").
LEAD_STRIP = {
    "try", "check", "consider", "visit", "see", "explore", "look", "contact", "call", "also",
    "and", "or", "near", "including", "like", "then", "both", "while", "at", "in", "with",
}
MIN_WORDS, MAX_WORDS = 2, 6
DISPLAY_MIN_RESPONSES = 2
EVIDENCE_KEEP = 20

_WORD = r"[A-Z][a-zA-Z'&-]*"
_SUFFIX_ALT = "|".join(re.escape(x) for x in sorted(SUFFIXES, key=len, reverse=True))
# The name must END at the suffix: not glued to a domain ("Apartments.com")
# and not continued by another capitalized word ("Sky Ridge Medical Center").
_END = r"(?![.\w]*\.[a-z]{2,})(?!\s+[A-Z])"
_SUFFIX_RE = re.compile(
    r"\b((?:The\s+)?%s(?:\s+(?:%s|at|on|of|the|&))*\s+(?:%s))\b%s" % (_WORD, _WORD, _SUFFIX_ALT, _END)
)
_AT_RE = re.compile(r"\b((?:The\s+)?(?:%s\s+){0,3}at\s+(?:the\s+)?%s(?:\s+%s){0,2})\b%s" % (_WORD, _WORD, _WORD, _END))
_BOLD_RE = re.compile(r"\*\*([^*\n]{3,80})\*\*")


def normalize_name(name: str) -> str:
    n = re.sub(r"[^a-z0-9 ]+", " ", name.lower())
    n = re.sub(r"^the\s+", "", n)
    return re.sub(r"\s+", " ", n).strip()


def _plausible(name: str) -> bool:
    words = name.split()
    if not (MIN_WORDS <= len(words) <= MAX_WORDS):
        return False
    if "." in name and re.search(r"\.[a-z]{2,}", name.lower()):
        return False  # a domain or brand like Apartments.com
    lead = words[1] if words[0].lower() == "the" and len(words) > 1 else words[0]
    if lead.lower().rstrip("s") in GENERIC_LEADS or lead.lower() in GENERIC_LEADS:
        return False
    return all(w[0].isupper() or w.lower() in {"at", "on", "of", "in", "the", "and", "&"} for w in words)


def _strip_lead(name: str, pos: int) -> tuple[str, int]:
    words = name.split()
    while len(words) > MIN_WORDS and words[0].lower() in LEAD_STRIP:
        pos = pos + len(words[0]) + 1
        words = words[1:]
    return " ".join(words), pos


def _community_shaped(name: str) -> bool:
    return " at " in f" {name} " or any(name.endswith(" " + sfx) for sfx in SUFFIXES)


def extract_candidate_names(text: str) -> list[tuple[str, int]]:
    """(display name, first position) in answer order, de-duplicated."""
    found: dict[str, tuple[str, int]] = {}
    for rx in (_AT_RE, _SUFFIX_RE):
        for m in rx.finditer(text or ""):
            name, pos = _strip_lead(m.group(1).strip(" .,:;-"), m.start(1))
            if _plausible(name):
                found.setdefault(normalize_name(name), (name, pos))
    for m in _BOLD_RE.finditer(text or ""):
        name, pos = _strip_lead(m.group(1).strip(" .,:;-"), m.start(1))
        # Bold alone is weak evidence (answers bold organizations and headings too).
        if _plausible(name) and _community_shaped(name):
            found.setdefault(normalize_name(name), (name, pos))
    # Drop a name contained in a longer name found at an overlapping spot.
    keys = sorted(found, key=len, reverse=True)
    kept: dict[str, tuple[str, int]] = {}
    for k in keys:
        if not any(k != big and k in big for big in kept):
            kept[k] = found[k]
    return sorted(kept.values(), key=lambda t: t[1])


def known_names_for_market(db: Session, market_id: int) -> set[str]:
    props = market_members(db, market_id)
    names: set[str] = set()
    for p in props:
        names.update(normalize_name(t) for t in resolve_property_terms(p))
    if props:
        for c in db.query(Competitor).filter(Competitor.property_id.in_([p.id for p in props])).all():
            names.update(normalize_name(t) for t in resolve_competitor_terms(c))
    return {n for n in names if n}


def _context(text: str, pos: int, width: int = 160) -> str:
    return " ".join((text or "")[max(0, pos - width // 2): pos + width].split())


def discover_from_response(
    db: Session, response: AIVisibilityQuery, market_id: int | None, known: set[str] | None = None
) -> list[AIDiscoveredEntity]:
    """Upsert candidates named in one response. Idempotent per response: a
    response already counted for an entity is not counted twice."""
    if market_id is None:
        return []
    known = known if known is not None else known_names_for_market(db, market_id)
    seen_at = response.executed_at or utcnow()
    rows: list[AIDiscoveredEntity] = []
    for display, pos in extract_candidate_names(response.raw_response_text or ""):
        norm = normalize_name(display)
        if not norm or norm in known or any(norm in k or k in norm for k in known if len(k) >= 6):
            continue
        row = db.query(AIDiscoveredEntity).filter_by(market_id=market_id, normalized_name=norm).one_or_none()
        if row is None:
            row = AIDiscoveredEntity(
                market_id=market_id, organization_id=response.organization_id, normalized_name=norm,
                display_name=display, entity_kind="community", first_seen=seen_at, last_seen=seen_at,
                mention_count=0, response_count=0, evidence_response_ids=[],
            )
            db.add(row)
            db.flush()
        evidence = list(row.evidence_response_ids or [])
        if response.id in evidence:
            continue
        evidence.append(response.id)
        row.evidence_response_ids = evidence[-EVIDENCE_KEEP:]
        row.response_count = (row.response_count or 0) + 1
        row.mention_count = (row.mention_count or 0) + 1
        row.last_seen = max(row.last_seen or seen_at, seen_at)
        row.first_seen = min(row.first_seen or seen_at, seen_at)
        row.sample_context = _context(response.raw_response_text, pos)
        rows.append(row)
    db.flush()
    return rows


def backfill_discovery(db: Session, market_id: int) -> dict:
    """Scan every stored answer in a market (shared market answers plus its
    properties' own runs)."""
    member_ids = [p.id for p in market_members(db, market_id)]
    conds = [AIVisibilityQuery.market_id == market_id]
    if member_ids:
        conds.append(AIVisibilityQuery.property_id.in_(member_ids))
    q = db.query(AIVisibilityQuery).filter(or_(*conds))
    known = known_names_for_market(db, market_id)
    scanned = 0
    for response in q.order_by(AIVisibilityQuery.id).all():
        discover_from_response(db, response, market_id, known)
        scanned += 1
    db.commit()
    total = db.query(AIDiscoveredEntity).filter_by(market_id=market_id).count()
    return {"market_id": market_id, "responses_scanned": scanned, "candidates": total}


def candidates_for_property(db: Session, property_id: int, include_decided: bool = False) -> list[dict]:
    prop = db.get(Property, property_id)
    if prop is None or prop.market_id is None:
        return []
    known = known_names_for_market(db, prop.market_id)
    decisions = {
        d.entity_id: d for d in db.query(AIEntityDecision).filter_by(property_id=property_id).all()
    }
    out = []
    rows = (
        db.query(AIDiscoveredEntity)
        .filter(AIDiscoveredEntity.market_id == prop.market_id,
                AIDiscoveredEntity.response_count >= DISPLAY_MIN_RESPONSES)
        .order_by(AIDiscoveredEntity.response_count.desc(), AIDiscoveredEntity.display_name)
        .all()
    )
    for e in rows:
        d = decisions.get(e.id)
        if d is None and e.normalized_name in known:
            continue  # tracked since discovery
        if d is not None and not include_decided:
            continue
        out.append({
            "id": e.id,
            "name": e.display_name,
            "responses": e.response_count,
            "first_seen": e.first_seen.isoformat() if e.first_seen else None,
            "last_seen": e.last_seen.isoformat() if e.last_seen else None,
            "evidence_response_ids": e.evidence_response_ids or [],
            "sample_context": e.sample_context,
            "confidence": round(min(1.0, (e.response_count or 0) / 5), 2),
            "confidence_label": LABEL_MODELED,
            "decision": d.decision if d else None,
            "competitor_id": d.competitor_id if d else None,
        })
    return out


def decide(
    db: Session, entity_id: int, property_id: int, decision: str, domain: str | None = None
) -> AIEntityDecision:
    if decision not in (DECISION_CONFIRMED, DECISION_IGNORED):
        raise ValueError("Decision must be confirmed or ignored.")
    entity = db.get(AIDiscoveredEntity, entity_id)
    prop = db.get(Property, property_id)
    if entity is None or prop is None:
        raise ValueError("Candidate or property not found.")
    if prop.market_id != entity.market_id:
        raise ValueError("That candidate was discovered in a different market.")
    row = db.query(AIEntityDecision).filter_by(entity_id=entity_id, property_id=property_id).one_or_none()
    if row is None:
        row = AIEntityDecision(entity_id=entity_id, property_id=property_id, decision=decision)
        db.add(row)
    row.decision = decision
    if decision == DECISION_CONFIRMED:
        comp = (
            db.query(Competitor).filter_by(property_id=property_id, name=entity.display_name).one_or_none()
        )
        if comp is None:
            comp = Competitor(property_id=property_id, name=entity.display_name, domain=domain or entity.domain)
            db.add(comp)
            db.flush()
        row.competitor_id = comp.id
    db.commit()
    return row
