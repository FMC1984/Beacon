"""Property Truth layer v1.

One row per fact Beacon holds about a property, one column per place that
fact can be stated: the recorded truth (with provenance), the property's own
site, the listing and directory pages AI answers cite, and the AI answers
themselves. Every cell comes from running the SAME deterministic claim
extractors Beacon already applies to AI answers over that source's text, so
"agrees" and "conflicts" mean the same thing in every column.

What this never does:
  * call a source wrong without a recorded fact that contradicts it;
  * treat an unread or blocked page as silent (it is "unread"/"unreachable");
  * grade a volatile fact (rent, availability) as a conflict; those need a
    live feed and are shown as volatile;
  * claim an origin for an AI error. It reports when a page the conflicting
    answer CITED states the same value, which is co-occurrence, labeled so.
"""

from collections import Counter, defaultdict
from datetime import date, datetime, timedelta

from sqlalchemy.orm import Session

from app.models import AICitation, AICitedPage, AIClaim, AIPropertyObservation, Competitor, Property, PropertyContent, PropertyFact
from app.models.ai_cited_pages import CHECK_OK
from app.models.ai_intelligence import CLAIM_CONFIRMED, CLAIM_CONFLICT, CLAIM_LIKELY_ACCURATE
from app.models.property_facts import FRESH_STABLE, FRESH_VOLATILE, FRESHNESS, STALE_AFTER
from app.services.ai_visibility.mentions import resolve_property_terms
from app.services.ai_visibility.parsing import find_mention
from app.services.jobs.queue import utcnow
from app.services.observatory import LABEL_MEASURED, utc_today
from app.services.observatory.citations import competitor_domains_for, owned_domains_for
from app.services.observatory.claims import (
    AMENITY_TERMS,
    _SENTENCE_SPLIT,
    _amenity_claims,
    _content_topics,
    _pet_claims,
    _rent_claims,
    _state_claims,
    _type_claims,
)
from app.services.observatory.tenancy import property_org_id
from app.services.property_context import get_property_context

MAX_LISTING_COLUMNS = 4
HOUSING_AUTHORITY = "housing_authority"

AGREES, CONFLICTS, MENTIONS, NOT_STATED = "agrees", "conflicts", "mentions", "not_stated"
UNREAD, UNREACHABLE, NOT_LISTED, VOLATILE = "unread", "unreachable", "not_listed", "volatile"


def _fact_key(claim_type: str, topic: str | None) -> str:
    return f"amenity:{topic}" if claim_type == "amenity" else claim_type


def _facts(prop: Property, ctx: dict) -> list[dict]:
    """The facts Beacon holds, from the places they already live."""
    attrs = prop.attributes or {}
    out = []
    if ctx.get("property_type"):
        out.append({"key": "property_type", "label": "Property type", "value": str(ctx["property_type"]).replace("_", " "),
                    "default_freshness": FRESH_STABLE})
    if prop.state:
        out.append({"key": "state", "label": "State", "value": prop.state, "default_freshness": FRESH_STABLE})
    if prop.property_type != HOUSING_AUTHORITY:
        if attrs.get("pet_policy"):
            out.append({"key": "pets", "label": "Pets", "value": str(attrs["pet_policy"]).replace("_", " "),
                        "default_freshness": FRESH_STABLE})
        rr = attrs.get("rent_range") or {}
        if rr.get("min") and rr.get("max"):
            out.append({"key": "rent", "label": "Rent range", "value": f"${int(rr['min']):,} to ${int(rr['max']):,}",
                        "default_freshness": FRESH_VOLATILE})
    recorded = [str(a).lower().replace("-", " ").replace("_", " ") for a in (attrs.get("amenities") or [])]
    for topic, terms in AMENITY_TERMS.items():
        if any(any(t in r or r in t for t in [topic.replace("_", " ")] + terms) for r in recorded):
            out.append({"key": f"amenity:{topic}", "label": topic.replace("_", " ").capitalize(), "value": "yes",
                        "default_freshness": FRESH_STABLE})
    return out


def _other_community_terms(db: Session, prop: Property) -> list[str]:
    """Names of other communities Beacon knows: tracked competitors and the
    other monitored properties in the same market."""
    names: set[str] = set()
    for c in db.query(Competitor).filter_by(property_id=prop.id).all():
        names.add(c.name)
        names.update(a for a in (c.aliases or []) if a)
    if prop.market_id is not None:
        for other in db.query(Property).filter(Property.market_id == prop.market_id, Property.id != prop.id).all():
            names.add(other.name)
            names.update(a for a in (other.aliases or []) if a)
    return sorted((n.strip() for n in names if n and n.strip()), key=len, reverse=True)


def _drafts(text: str, prop: Property, ctx: dict, content_topics: set[str], terms: list[str], require_mention: bool,
            other_terms: list[str] | None = None):
    """The claim extractors over any source text. On third-party pages only
    sentences that name the property count; on the property's own pages
    every sentence is about the property."""
    attrs = prop.attributes or {}
    drafts = []
    for sentence in (s.strip() for s in _SENTENCE_SPLIT.split(text or "") if s.strip()):
        if require_mention and not find_mention(sentence, terms):
            continue
        # A sentence that also names another community (a directory's list of
        # featured properties, a comparison) cannot be attributed to this one:
        # "Lakemont Senior Residences, Stonebrook Commons" does not make
        # Stonebrook senior housing. Skipped rather than guessed.
        if require_mention and other_terms and find_mention(sentence, other_terms):
            continue
        drafts += _type_claims(sentence, ctx) + _state_claims(sentence, prop)
        drafts += _pet_claims(sentence, attrs) + _amenity_claims(sentence, attrs, content_topics) + _rent_claims(sentence, attrs)
    return drafts


def _cell_from_drafts(drafts, fact_key: str, volatile: bool) -> dict:
    mine = [d for d in drafts if _fact_key(d.claim_type, d.topic) == fact_key]
    if not mine:
        return {"state": NOT_STATED}
    values = sorted({d.value for d in mine})
    if volatile:
        return {"state": VOLATILE, "values": values}
    if any(d.status == CLAIM_CONFLICT for d in mine):
        bad = next(d for d in mine if d.status == CLAIM_CONFLICT)
        return {"state": CONFLICTS, "values": values, "evidence": bad.text[:240]}
    if any(d.status in (CLAIM_CONFIRMED, CLAIM_LIKELY_ACCURATE) for d in mine):
        return {"state": AGREES, "values": values}
    return {"state": MENTIONS, "values": values}


def _provenance(row: PropertyFact | None, default_freshness: str, now: datetime) -> dict:
    fresh = (row.freshness if row else None) or default_freshness
    verified = row.verified_at if row else None
    if verified is None:
        status = "unverified"
    elif now - verified > timedelta(days=STALE_AFTER.get(fresh, 180)):
        status = "stale"
    else:
        status = "verified"
    return {
        "source_of_truth": row.source_of_truth if row else None,
        "verified_at": verified.isoformat() if verified else None,
        "verified_by": row.verified_by if row else None,
        "effective_date": row.effective_date.isoformat() if row and row.effective_date else None,
        "freshness": fresh, "status": status, "stale_after_days": STALE_AFTER.get(fresh, 180),
        "notes": row.notes if row else None,
    }


def truth_grid(db: Session, property_id: int, days: int = 90, today: date | None = None) -> dict:
    prop = db.get(Property, property_id)
    if prop is None:
        raise ValueError("Property not found.")
    today = today or utc_today()
    now = utcnow()
    ctx = get_property_context(db, property_id)
    facts = _facts(prop, ctx)
    terms = resolve_property_terms(prop)
    content_topics = _content_topics(db, property_id)
    prov = {r.fact_key: r for r in db.query(PropertyFact).filter_by(property_id=property_id).all()}

    # Columns: own site, then the most-cited third-party domains in the window.
    lo = datetime.combine(today - timedelta(days=days - 1), datetime.min.time())
    hi = datetime.combine(today + timedelta(days=1), datetime.min.time())
    cites = (
        db.query(AICitation.domain, AICitation.normalized_url)
        .join(AIPropertyObservation, AIPropertyObservation.response_id == AICitation.response_id)
        .filter(AIPropertyObservation.property_id == property_id, AIPropertyObservation.eligible.is_(True),
                AIPropertyObservation.observed_at >= lo, AIPropertyObservation.observed_at < hi)
        .all()
    )
    owned = owned_domains_for(prop)
    comp = competitor_domains_for(db.query(Competitor).filter_by(property_id=property_id).all())
    by_domain: Counter = Counter()
    urls: dict[str, set] = defaultdict(set)
    for dom, nurl in cites:
        if any(dom == d or dom.endswith("." + d) for d in owned | comp):
            continue
        by_domain[dom] += 1
        urls[dom].add(nurl)
    listing_domains = [d for d, _ in by_domain.most_common(MAX_LISTING_COLUMNS)]
    all_urls = [u for d in listing_domains for u in urls[d]]
    cached = {p.normalized_url: p for p in db.query(AICitedPage).filter(AICitedPage.normalized_url.in_(all_urls)).all()} if all_urls else {}

    site_pages = db.query(PropertyContent).filter_by(property_id=property_id).all()
    others = _other_community_terms(db, prop)
    site_drafts = _drafts(" ".join(f"{p.title or ''}. {p.body or ''}" for p in site_pages), prop, ctx, content_topics, terms, False)

    listing_state: dict[str, dict] = {}
    for dom in listing_domains:
        pages = [cached[u] for u in urls[dom] if u in cached]
        readable = [p for p in pages if p.status == CHECK_OK]
        if not pages:
            listing_state[dom] = {"fixed": UNREAD}
        elif not readable:
            listing_state[dom] = {"fixed": UNREACHABLE}
        elif not any(find_mention(p.body or "", terms) for p in readable):
            listing_state[dom] = {"fixed": NOT_LISTED}
        else:
            listing_state[dom] = {"drafts": _drafts(" ".join(p.body or "" for p in readable), prop, ctx, content_topics, terms, True, others)}

    claims = db.query(AIClaim).filter(AIClaim.property_id == property_id, AIClaim.status == "open").all()
    claims_by_fact: dict[str, list[AIClaim]] = defaultdict(list)
    for c in claims:
        claims_by_fact[_fact_key(c.claim_type, c.claim_topic)].append(c)

    rows = []
    for f in facts:
        p = _provenance(prov.get(f["key"]), f["default_freshness"], now)
        volatile = p["freshness"] == FRESH_VOLATILE
        cells = {"website": ({"state": UNREAD} if not site_pages else _cell_from_drafts(site_drafts, f["key"], volatile))}
        for dom in listing_domains:
            st = listing_state[dom]
            cells[dom] = {"state": st["fixed"]} if "fixed" in st else _cell_from_drafts(st["drafts"], f["key"], volatile)
        ai = claims_by_fact.get(f["key"], [])
        agree = sum(c.occurrence_count for c in ai if c.verification_status in (CLAIM_CONFIRMED, CLAIM_LIKELY_ACCURATE))
        conflict = sum(c.occurrence_count for c in ai if c.verification_status == CLAIM_CONFLICT)
        if not ai:
            ai_cell = {"state": NOT_STATED}
        elif volatile:
            ai_cell = {"state": VOLATILE, "values": sorted({c.claim_value for c in ai})}
        elif conflict:
            ai_cell = {"state": CONFLICTS, "agree": agree, "conflict": conflict,
                       "values": sorted({c.claim_value for c in ai if c.verification_status == CLAIM_CONFLICT})}
        else:
            ai_cell = {"state": AGREES if agree else MENTIONS, "agree": agree, "conflict": 0}
        cells["ai_answers"] = ai_cell

        # Co-occurrence only: did a page the conflicting answers CITED state the same value?
        origins = []
        if ai_cell["state"] == CONFLICTS:
            rids = {rid for c in ai if c.verification_status == CLAIM_CONFLICT for rid in (c.response_ids or [])}
            wrong = set(ai_cell["values"])
            if rids:
                cited = {n for (n,) in db.query(AICitation.normalized_url).filter(AICitation.response_id.in_(list(rids))).distinct()}
                for page in db.query(AICitedPage).filter(AICitedPage.normalized_url.in_(list(cited)), AICitedPage.status == CHECK_OK).all():
                    for d in _drafts(page.body or "", prop, ctx, content_topics, terms, True, others):
                        if _fact_key(d.claim_type, d.topic) == f["key"] and d.status == CLAIM_CONFLICT and d.value in wrong:
                            origins.append({"domain": page.domain, "url": page.normalized_url, "value": d.value, "evidence": d.text[:240]})
                            break
        states = [c["state"] for c in cells.values()]
        rows.append({
            "fact_key": f["key"], "label": f["label"], "recorded_value": f["value"], "provenance": p, "cells": cells,
            "conflicts": states.count(CONFLICTS),
            "cited_sources_with_same_value": origins,
        })
    rows.sort(key=lambda r: (-r["conflicts"], r["provenance"]["status"] == "verified", r["label"]))
    notes = []
    if prop.property_type == HOUSING_AUTHORITY:
        notes.append("Housing authorities hold different policies per development. Pets and rent are not graded here until facts can be recorded per development.")
    return {
        "property_id": property_id, "data_label": LABEL_MEASURED,
        "window": {"start": (today - timedelta(days=days - 1)).isoformat(), "end": today.isoformat(), "days": days},
        "columns": [{"key": "website", "label": "Your website", "kind": "owned"}]
                   + [{"key": d, "label": d, "kind": "listing", "citations": by_domain[d]} for d in listing_domains]
                   + [{"key": "ai_answers", "label": "AI answers", "kind": "ai"}],
        "facts": rows,
        "summary": {
            "facts": len(rows), "with_conflicts": sum(1 for r in rows if r["conflicts"]),
            "unverified": sum(1 for r in rows if r["provenance"]["status"] == "unverified"),
            "stale": sum(1 for r in rows if r["provenance"]["status"] == "stale"),
        },
        "notes": notes,
        "note": ("Each cell is the same deterministic check Beacon runs on AI answers, applied to that source's text. "
                 "A source Beacon could not read is unread or unreachable, never silent. Rent is volatile and never graded. "
                 "'Cited source shows the same value' means a page the conflicting answer cited states it too; it is not proof of origin."),
    }


def set_provenance(db: Session, property_id: int, fact_key: str, *, source_of_truth=None, verified: bool | None = None,
                   verified_by=None, effective_date: date | None = None, freshness: str | None = None, notes=None) -> dict:
    prop = db.get(Property, property_id)
    if prop is None:
        raise ValueError("Property not found.")
    known = {f["key"]: f for f in _facts(prop, get_property_context(db, property_id))}
    if fact_key not in known:
        raise LookupError("Beacon holds no such fact for this property. Record the value first (Properties or Property Context).")
    if freshness is not None and freshness not in FRESHNESS:
        raise ValueError(f"freshness must be one of {', '.join(FRESHNESS)}.")
    row = db.query(PropertyFact).filter_by(property_id=property_id, fact_key=fact_key).one_or_none()
    if row is None:
        row = PropertyFact(property_id=property_id, organization_id=property_org_id(db, property_id), fact_key=fact_key,
                           freshness=known[fact_key]["default_freshness"])
        db.add(row)
    now = utcnow()
    if source_of_truth is not None:
        row.source_of_truth = source_of_truth.strip()[:200] or None
    if verified_by is not None:
        row.verified_by = verified_by.strip()[:120] or None
    if effective_date is not None:
        row.effective_date = effective_date
    if freshness is not None:
        row.freshness = freshness
    if notes is not None:
        row.notes = notes.strip() or None
    if verified is True:
        row.verified_at = now
    elif verified is False:
        row.verified_at = None
    row.updated_at = now
    db.commit()
    return _provenance(row, known[fact_key]["default_freshness"], now)
