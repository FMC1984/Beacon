"""Prompt library generation (Phase 19, slice 2).

Builds a property's initial prompt universe without a marketer writing a
hundred prompts, from: templates (market / feature / brand), the taxonomy,
the property's own attributes and site content topics, tracked competitors,
and Search Console queries when connected (as a topic signal only - Beacon
does not turn keyword strings into fabricated questions). Every generated
prompt keeps provenance (generated_from, generation_method) and is
de-duplicated by text hash within its scope, so re-generation is idempotent.

Market and feature prompts are created ONCE per market and shared; a
property is *assigned* to the clusters that matter for it (assignments.py).
"""

import hashlib
import json
from dataclasses import dataclass, field
from functools import lru_cache
from pathlib import Path

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import (
    AIVisibilityPrompt,
    Competitor,
    GSCPerformanceDaily,
    Market,
    Property,
    PropertyContent,
)
from app.models.ai_prompt_library import (
    PROMPT_SCOPE_BRAND,
    PROMPT_SCOPE_FEATURE,
    PROMPT_SCOPE_MARKET,
)
from app.services.observatory.markets import assign_property_market
from app.services.observatory.taxonomy import (
    core_topic_keys,
    topic,
    topics_for_semantic,
    topics_in_text,
)
from app.services.observatory.tenancy import property_org_id

_TEMPLATES = Path(__file__).resolve().parent.parent.parent / "reference_data" / "ai_prompt_templates.json"

GSC_SIGNAL_QUERY_LIMIT = 50
MAX_COMPETITOR_PROMPTS = 3


@lru_cache(maxsize=1)
def templates() -> dict:
    return json.loads(_TEMPLATES.read_text())


def prompt_hash(text: str) -> str:
    return hashlib.sha256(" ".join((text or "").split()).lower().encode("utf-8")).hexdigest()


@dataclass
class PromptDraft:
    text: str
    scope: str
    topic_key: str | None
    intent: str | None
    importance: int
    funnel_stage: str | None
    variant_group: str
    is_representative: bool
    generated_from: dict
    generation_method: str = "template"
    market_id: int | None = None
    property_id: int | None = None
    organization_id: int | None = None
    platform: str = "chatgpt"
    tags: list[str] = field(default_factory=list)


def _fill(text: str, values: dict) -> str | None:
    """Fill placeholders; None when a required placeholder has no value (a
    half-filled prompt is never emitted)."""
    out = text
    for key, value in values.items():
        token = "{" + key + "}"
        if token in out:
            if not value:
                return None
            out = out.replace(token, str(value))
    if "{" in out and "}" in out:
        return None
    return out


def upsert_prompt(db: Session, draft: PromptDraft) -> tuple[AIVisibilityPrompt, bool]:
    """Idempotent by (hash, scope, market, property). Existing rows keep
    operator edits (active/approved/importance) and only refresh provenance."""
    h = prompt_hash(draft.text)
    q = db.query(AIVisibilityPrompt).filter(
        AIVisibilityPrompt.prompt_hash == h,
        AIVisibilityPrompt.scope == draft.scope,
    )
    q = q.filter(AIVisibilityPrompt.market_id == draft.market_id) if draft.market_id is not None else q.filter(AIVisibilityPrompt.market_id.is_(None))
    q = q.filter(AIVisibilityPrompt.property_id == draft.property_id) if draft.property_id is not None else q.filter(AIVisibilityPrompt.property_id.is_(None))
    existing = q.first()
    if existing is not None:
        existing.generated_from = draft.generated_from
        existing.topic_key = existing.topic_key or draft.topic_key
        return existing, False
    row = AIVisibilityPrompt(
        property_id=draft.property_id,
        market_id=draft.market_id,
        organization_id=draft.organization_id,
        platform=draft.platform,
        prompt_text=draft.text,
        active=True,
        scope=draft.scope,
        topic_key=draft.topic_key,
        intent=draft.intent,
        importance=draft.importance,
        funnel_stage=draft.funnel_stage,
        generated_from=draft.generated_from,
        generation_method=draft.generation_method,
        approved=True,
        repeat_count=1,
        prompt_hash=h,
        is_representative=draft.is_representative,
        variant_group=draft.variant_group,
        tags=draft.tags or None,
        cadence="weekly" if draft.scope in (PROMPT_SCOPE_MARKET, PROMPT_SCOPE_FEATURE) else "monthly",
    )
    db.add(row)
    db.flush()
    return row, True


def _template_drafts(entries: list[dict], scope: str, values: dict, *, market_id, property_id,
                     organization_id, provenance: dict) -> list[PromptDraft]:
    drafts: list[PromptDraft] = []
    for entry in entries:
        t = topic(entry.get("topic_key")) or {}
        primary = _fill(entry["text"], values)
        if primary is None:
            continue
        group = f"{entry['id']}:{market_id or ''}:{property_id or ''}"
        base = dict(
            scope=scope, topic_key=entry.get("topic_key"), intent=entry.get("intent"),
            importance=int(entry.get("importance") or t.get("importance") or 3),
            funnel_stage=t.get("funnel_stage"), variant_group=group,
            market_id=market_id, property_id=property_id, organization_id=organization_id,
        )
        drafts.append(PromptDraft(
            text=primary, is_representative=True,
            generated_from={**provenance, "template_id": entry["id"], "variant": 0}, **base,
        ))
        for i, variant in enumerate(entry.get("variants") or [], start=1):
            text = _fill(variant, values)
            if text is None or text == primary:
                continue
            drafts.append(PromptDraft(
                text=text, is_representative=False,
                generated_from={**provenance, "template_id": entry["id"], "variant": i}, **base,
            ))
    return drafts


def generate_market_prompts(db: Session, market_id: int) -> dict:
    """Create the shared market + feature prompt universe for a market.
    Idempotent; returns counts and the prompts touched."""
    market = db.get(Market, market_id)
    if market is None:
        raise ValueError("Market not found.")
    values = {"city": market.city, "state": market.state}
    provenance = {"generation_method": "template", "market_id": market.id, "inputs": values}
    tpl = templates()
    drafts = _template_drafts(
        tpl["market"], PROMPT_SCOPE_MARKET, values,
        market_id=market.id, property_id=None, organization_id=market.organization_id,
        provenance=provenance,
    ) + _template_drafts(
        tpl["feature"], PROMPT_SCOPE_FEATURE, values,
        market_id=market.id, property_id=None, organization_id=market.organization_id,
        provenance=provenance,
    )
    created = 0
    prompts = []
    for draft in drafts:
        row, was_created = upsert_prompt(db, draft)
        created += int(was_created)
        prompts.append(row)
    db.commit()
    return {"market_id": market.id, "prompts_total": len(prompts), "prompts_created": created,
            "prompts": prompts}


def property_signal_topics(db: Session, prop: Property) -> dict:
    """Which taxonomy topics this property has evidence for, and why.
    Signals: operator attributes, site content topics, Search Console
    queries (connected data only). Core topics always apply."""
    reasons: dict[str, set[str]] = {}

    def add(keys, why):
        for k in keys:
            reasons.setdefault(k, set()).add(why)

    add(core_topic_keys(), "core")
    attrs = prop.attributes or {}
    attr_text = " ".join(
        str(v) for v in [
            " ".join(attrs.get("amenities") or []) if isinstance(attrs.get("amenities"), list) else attrs.get("amenities"),
            json.dumps(attrs.get("pet_policy")) if attrs.get("pet_policy") else "",
            attrs.get("segment") or "", attrs.get("neighborhood") or "",
            " ".join(attrs.get("floor_plans") or []) if isinstance(attrs.get("floor_plans"), list) else "",
        ] if v
    )
    if attr_text:
        add(topics_in_text(attr_text), "attributes")
    if prop.property_type == "housing_authority":
        add(["affordable"], "property_type")
    for row in db.query(PropertyContent).filter_by(property_id=prop.id).all():
        add(topics_for_semantic(row.topics), "content")
        add(topics_in_text(row.body or ""), "content")
    gsc = (
        db.query(GSCPerformanceDaily.query, func.sum(GSCPerformanceDaily.impressions))
        .filter(GSCPerformanceDaily.property_id == prop.id, GSCPerformanceDaily.query.isnot(None))
        .group_by(GSCPerformanceDaily.query)
        .order_by(func.sum(GSCPerformanceDaily.impressions).desc())
        .limit(GSC_SIGNAL_QUERY_LIMIT)
        .all()
    )
    if gsc:
        add(topics_in_text(" ".join(q for q, _ in gsc)), "gsc")
    return {k: sorted(v) for k, v in reasons.items()}


def generate_property_prompts(db: Session, property_id: int) -> dict:
    """Brand prompts for one property (plus competitor comparisons), and the
    shared market universe for its market. Idempotent."""
    prop = db.get(Property, property_id)
    if prop is None:
        raise ValueError("Property not found.")
    if prop.market_id is None:
        assign_property_market(db, prop)
        db.flush()
    org_id = property_org_id(db, property_id)
    values = {"name": prop.name, "city": prop.city, "state": prop.state}
    provenance = {"generation_method": "template", "property_id": prop.id, "inputs": values}
    tpl = templates()
    entries = tpl["brand"].get(prop.property_type) or tpl["brand"]["multifamily_apartment"]
    drafts = _template_drafts(
        entries, PROMPT_SCOPE_BRAND, values,
        market_id=prop.market_id, property_id=prop.id, organization_id=org_id,
        provenance=provenance,
    )
    competitors = (
        db.query(Competitor).filter_by(property_id=prop.id).order_by(Competitor.name)
        .limit(MAX_COMPETITOR_PROMPTS).all()
    )
    vs = tpl.get("brand_competitor")
    for comp in competitors:
        text = _fill(vs["text"], {**values, "competitor": comp.name})
        if text:
            drafts.append(PromptDraft(
                text=text, scope=PROMPT_SCOPE_BRAND, topic_key=vs.get("topic_key"),
                intent=vs.get("intent"), importance=3, funnel_stage="decision",
                variant_group=f"{vs['id']}:{prop.id}:{comp.id}", is_representative=True,
                generated_from={**provenance, "template_id": vs["id"], "competitor_id": comp.id},
                market_id=prop.market_id, property_id=prop.id, organization_id=org_id,
            ))
    created = 0
    prompts = []
    for draft in drafts:
        row, was_created = upsert_prompt(db, draft)
        created += int(was_created)
        prompts.append(row)
    db.commit()

    market_summary = generate_market_prompts(db, prop.market_id) if prop.market_id else None
    return {
        "property_id": prop.id,
        "market_id": prop.market_id,
        "brand_prompts_total": len(prompts),
        "brand_prompts_created": created,
        "market_prompts_total": market_summary["prompts_total"] if market_summary else 0,
        "market_prompts_created": market_summary["prompts_created"] if market_summary else 0,
        "signal_topics": property_signal_topics(db, prop),
        "prompts": prompts,
    }
