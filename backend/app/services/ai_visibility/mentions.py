"""Alias-aware mention extraction and persistence (Phase 18 Share of Voice).

Turns a stored AI response into individual Mention rows: at most one row per
entity (the property, or each competitor) actually found in the text,
recording which specific alias matched (raw_matched_text) versus the
canonical name it rolls up to (normalized_name). This is the explainability
requirement - an evidence drawer can say *why* a mention was attributed to
an entity ("matched via alias 'Collective on 13th'") instead of just
asserting it.

Detection reuses parsing.find_mention(), the same deterministic whole-word/
phrase regex as detect_mention()/analyze_share_of_voice() - no fuzzy
matching, no LLM judge. Property and competitor terms are both
operator-asserted (Property.aliases / Competitor.aliases); Beacon never
infers an alias.

Presence semantics match the existing analyzer: a response either mentions
an entity or it does not (this is not a word-count), so exactly zero or one
Mention row is created per (response, entity) pair. `match_count` on that
row is the raw occurrence count within the response - evidence only, never
summed into the Share of Voice formula itself.

Failed-execution persistence is deliberately out of scope for this phase
(Phase 18 decision): AIVisibilityQuery.execution_status exists in the schema
but run_query() only ever writes "success" rows today, same as before this
feature. Mention extraction therefore only ever runs against successful,
already-stored responses.
"""

from sqlalchemy.orm import Session

from app.models import (
    ENTITY_COMPETITOR,
    ENTITY_PROPERTY,
    AIVisibilityQuery,
    Competitor,
    Mention,
    Property,
)
from app.services.ai_visibility.parsing import find_mention


def resolve_property_terms(prop: Property) -> list[str]:
    """Property name plus operator-asserted aliases, de-duplicated and
    sorted longest-first so the most specific alias is what gets recorded as
    the matched text when more than one would match."""
    if not prop or not prop.name:
        return []
    terms = {prop.name.strip()} | {a.strip() for a in (prop.aliases or []) if a and a.strip()}
    return sorted(terms, key=len, reverse=True)


def resolve_competitor_terms(comp: Competitor) -> list[str]:
    terms = {comp.name.strip()} | {a.strip() for a in (comp.aliases or []) if a and a.strip()}
    return sorted(terms, key=len, reverse=True)


def extract_mentions(
    query: AIVisibilityQuery, prop: Property, competitors: list[Competitor]
) -> list[Mention]:
    """Unsaved Mention rows for one stored response."""
    text = query.raw_response_text or ""
    rows: list[Mention] = []

    prop_match = find_mention(text, resolve_property_terms(prop))
    if prop_match:
        rows.append(
            Mention(
                response_id=query.id,
                entity_type=ENTITY_PROPERTY,
                entity_id=prop.id,
                normalized_name=prop.name,
                raw_matched_text=prop_match["term"],
                match_count=prop_match["count"],
                position=prop_match["position"],
            )
        )

    for comp in competitors:
        comp_match = find_mention(text, resolve_competitor_terms(comp))
        if comp_match:
            rows.append(
                Mention(
                    response_id=query.id,
                    entity_type=ENTITY_COMPETITOR,
                    entity_id=comp.id,
                    normalized_name=comp.name,
                    raw_matched_text=comp_match["term"],
                    match_count=comp_match["count"],
                    position=comp_match["position"],
                )
            )
    return rows


def persist_mentions_for_query(db: Session, query: AIVisibilityQuery) -> list[Mention]:
    """Extracts and saves Mention rows for one query, updating its
    denormalized property_mention_count/competitor_mention_count (presence
    counts - 1 if the property was mentioned, and how many distinct
    competitors were mentioned - matching the per-response counting
    analyze_share_of_voice already uses) so report reads never COUNT the
    mentions table per response.

    Idempotent: clears any existing rows for this response first, so this is
    safe to call from both run_query() and the backfill script, including
    re-running after an alias edit."""
    prop = db.get(Property, query.property_id)
    if prop is None:
        return []
    competitors = db.query(Competitor).filter_by(property_id=query.property_id).all()

    db.query(Mention).filter_by(response_id=query.id).delete()

    rows = extract_mentions(query, prop, competitors)
    for row in rows:
        db.add(row)

    query.property_mention_count = 1 if any(
        r.entity_type == ENTITY_PROPERTY for r in rows
    ) else 0
    query.competitor_mention_count = sum(
        1 for r in rows if r.entity_type == ENTITY_COMPETITOR
    )
    db.commit()
    return rows


def backfill_mentions(
    db: Session, property_id: int | None = None, batch_size: int = 500
) -> dict:
    """One-time (idempotent, re-runnable) walk of existing AIVisibilityQuery
    rows to populate Mention rows for history that predates this feature, so
    Share of Voice trend/history has real data on day one instead of
    starting empty."""
    q = db.query(AIVisibilityQuery)
    if property_id is not None:
        q = q.filter(AIVisibilityQuery.property_id == property_id)
    total = q.count()
    processed = 0
    offset = 0
    while True:
        batch = (
            q.order_by(AIVisibilityQuery.id)
            .offset(offset)
            .limit(batch_size)
            .all()
        )
        if not batch:
            break
        for query in batch:
            persist_mentions_for_query(db, query)
            processed += 1
        offset += batch_size
    return {"queries_total": total, "queries_processed": processed}
