"""Derived per-property observations (Phase 19, slice 3).

One stored response -> one AIPropertyObservation per eligible property,
computed in code from Mention + AICitation rows. This is the cost lever of
the whole Observatory: a market prompt runs once and every subscribed
property gets scored from the same answer. Idempotent: deriving the same
response again replaces its rows (re-run after alias/domain edits via
rederive_response).
"""

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models import (
    ENTITY_COMPETITOR,
    ENTITY_PROPERTY,
    AICitation,
    AIPropertyObservation,
    AIRun,
    AIVisibilityPrompt,
    AIVisibilityQuery,
    Competitor,
    Mention,
    Property,
)
from app.models.ai_observations import DERIVATION_VERSION
from app.services.ai_visibility.mentions import resolve_property_terms
from app.services.observatory.assignments import properties_for_cluster
from app.services.observatory.citations import competitor_domains_for, domain_of_url
from app.services.observatory.markets import market_members
from app.services.observatory.recommendation import classify_recommendation
from app.services.observatory.sentiment import mention_sentiment
from app.services.observatory.tenancy import property_org_id

ELIGIBLE_PROPERTY_RUN = "property_run"
ELIGIBLE_CLUSTER_ASSIGNMENT = "cluster_assignment"
ELIGIBLE_MARKET_MEMBER = "market_member"


def eligible_properties(
    db: Session, run: AIRun, prompt: AIVisibilityPrompt | None
) -> list[tuple[Property, str]]:
    """Who a response can be scored for. A property run scores its own
    property. A market run scores the properties subscribed to the prompt's
    cluster; with no cluster yet, every active property in the market."""
    if run.property_id is not None:
        prop = db.get(Property, run.property_id)
        return [(prop, ELIGIBLE_PROPERTY_RUN)] if prop is not None else []
    if run.market_id is None:
        return []
    if prompt is not None and prompt.cluster_id is not None:
        ids = properties_for_cluster(db, prompt.cluster_id)
        if ids:
            props = db.query(Property).filter(Property.id.in_(ids), Property.is_active.is_(True)).all()
            return [(p, ELIGIBLE_CLUSTER_ASSIGNMENT) for p in sorted(props, key=lambda p: p.id)]
    return [(p, ELIGIBLE_MARKET_MEMBER) for p in market_members(db, run.market_id)]


def _domain_matches(domain: str, owned: set[str]) -> bool:
    return any(domain == o or domain.endswith("." + o) for o in owned)


def derive_observations(
    db: Session, response: AIVisibilityQuery, run: AIRun | None,
    properties: list[tuple[Property, str]] | None = None,
) -> list[AIPropertyObservation]:
    """Replace the response's derived rows. `properties` defaults to the
    run's eligibility list."""
    prompt = db.get(AIVisibilityPrompt, response.prompt_id) if response.prompt_id else None
    if properties is None:
        if run is None:
            prop = db.get(Property, response.property_id) if response.property_id else None
            properties = [(prop, ELIGIBLE_PROPERTY_RUN)] if prop else []
        else:
            properties = eligible_properties(db, run, prompt)

    mentions = db.query(Mention).filter_by(response_id=response.id).order_by(Mention.position).all()
    citations = db.query(AICitation).filter_by(response_id=response.id).order_by(AICitation.citation_order).all()
    prop_ids = [p.id for p, _ in properties]
    competitors_by_prop: dict[int, list[Competitor]] = {pid: [] for pid in prop_ids}
    if prop_ids:
        for c in db.query(Competitor).filter(Competitor.property_id.in_(prop_ids)).all():
            competitors_by_prop.setdefault(c.property_id, []).append(c)

    # Rank every named entity by first position in the answer.
    ranked = sorted((m for m in mentions if m.position is not None), key=lambda m: m.position)
    rank_of: dict[tuple[str, int], int] = {}
    for i, m in enumerate(ranked, start=1):
        rank_of.setdefault((m.entity_type, m.entity_id), i)

    db.query(AIPropertyObservation).filter_by(response_id=response.id).delete()
    text = response.raw_response_text or ""
    rows: list[AIPropertyObservation] = []
    for prop, reason in properties:
        own_mention = next(
            (m for m in mentions if m.entity_type == ENTITY_PROPERTY and m.entity_id == prop.id), None
        )
        comps = competitors_by_prop.get(prop.id, [])
        comp_ids = {c.id for c in comps}
        comp_mentions = [m for m in mentions if m.entity_type == ENTITY_COMPETITOR and m.entity_id in comp_ids]
        owned = {d for d in [prop.domain or domain_of_url(prop.website_url)] if d}
        comp_domains = competitor_domains_for(comps)
        own_cites = [c for c in citations if owned and _domain_matches(c.domain, owned)]
        comp_cites = [c for c in citations if comp_domains and _domain_matches(c.domain, comp_domains)]

        mentioned = own_mention is not None
        position = own_mention.position if own_mention else None
        rank = rank_of.get((ENTITY_PROPERTY, prop.id)) if own_mention else None
        recommended, method, _rules = classify_recommendation(
            text, mentioned=mentioned, mention_position=position, mention_rank=rank
        )
        label, score, excerpt = (
            mention_sentiment(text, position, resolve_property_terms(prop)) if mentioned else (None, None, None)
        )
        row = AIPropertyObservation(
            organization_id=run.organization_id if run and run.organization_id else property_org_id(db, prop.id),
            property_id=prop.id,
            response_id=response.id,
            run_id=run.id if run else None,
            prompt_id=response.prompt_id,
            cluster_id=prompt.cluster_id if prompt else None,
            market_id=run.market_id if run and run.market_id else prop.market_id,
            platform=response.platform,
            provider=response.provider,
            observed_at=response.executed_at,
            eligible=True,
            eligibility_reason=reason,
            mentioned=mentioned,
            mention_position=position,
            mention_rank=rank,
            mention_confidence=own_mention.confidence if own_mention else None,
            cited=bool(own_cites),
            citation_count=len(own_cites),
            citation_first_order=own_cites[0].citation_order if own_cites else None,
            matched_citation_ids=[c.id for c in own_cites] or None,
            recommended=recommended,
            recommendation_method=method if mentioned else None,
            sentiment=label,
            sentiment_score=score,
            context_excerpt=excerpt,
            competitor_mentioned_count=len(comp_mentions),
            competitor_cited_count=len(comp_cites),
            competitor_entity_ids=[m.entity_id for m in comp_mentions] or None,
            total_citation_count=len(citations),
            derivation_version=DERIVATION_VERSION,
            rolled_up=False,
        )
        if own_mention is not None:
            own_mention.recommended = recommended
            own_mention.sentiment = label
            own_mention.sentiment_score = score
            own_mention.context_excerpt = excerpt
            own_mention.mention_type = "both" if own_cites else "named"
        db.add(row)
        rows.append(row)
    db.flush()
    return rows


def refresh_mentions(db: Session, response: AIVisibilityQuery, run: AIRun | None) -> None:
    """Re-detect the response's Mention rows from its stored text (cheap,
    deterministic, no provider call): property responses through the
    legacy per-property extractor, shared market responses against every
    eligible property and its tracked competitors."""
    from app.services.ai_visibility.mentions import persist_mentions_for_query
    from app.services.observatory.entities import (
        detect_entity_mentions,
        entities_for_properties,
        persist_entity_mentions,
    )

    if response.property_id is not None:
        persist_mentions_for_query(db, response)
        return
    if run is None:
        return
    prompt = db.get(AIVisibilityPrompt, response.prompt_id) if response.prompt_id else None
    props = [p for p, _ in eligible_properties(db, run, prompt)]
    entities = entities_for_properties(db, props)
    persist_entity_mentions(db, response, run, detect_entity_mentions(response.raw_response_text or "", entities))
    db.commit()


def rederive_response(db: Session, response_id: int) -> list[AIPropertyObservation]:
    """Recompute mentions then observations for one response (after alias,
    domain, competitor or subscription edits)."""
    response = db.get(AIVisibilityQuery, response_id)
    if response is None:
        raise ValueError("Response not found.")
    run = db.get(AIRun, response.run_id) if response.run_id else None
    refresh_mentions(db, response, run)
    rows = derive_observations(db, response, run)
    db.commit()
    return rows


def backfill_observations(db: Session, property_id: int | None = None, batch_size: int = 200) -> dict:
    """Derive observations for every stored response that has none yet
    (history from before slice 3). Idempotent and resumable."""
    q = db.query(AIVisibilityQuery.id)
    if property_id is not None:
        q = q.filter(AIVisibilityQuery.property_id == property_id)
    derived_ids = {rid for (rid,) in db.query(AIPropertyObservation.response_id).distinct()}
    todo = [rid for (rid,) in q.order_by(AIVisibilityQuery.id).all() if rid not in derived_ids]
    processed = 0
    for i in range(0, len(todo), batch_size):
        for rid in todo[i:i + batch_size]:
            response = db.get(AIVisibilityQuery, rid)
            run = db.get(AIRun, response.run_id) if response.run_id else None
            # History from before Phase 18 may have no Mention rows at all.
            if not db.query(Mention.id).filter_by(response_id=rid).first():
                refresh_mentions(db, response, run)
            derive_observations(db, response, run)
            processed += 1
        db.commit()
    return {"responses_total": len(todo), "responses_processed": processed,
            "processed_at": datetime.now(timezone.utc).isoformat()}
