"""Chunk/document enrichment (Phase 15a).

enrich_text() produces the structured metadata stamped on every indexed chunk:
topics, entities, intents, per-topic sentiment, normalized terms. Everything is
derived from the semantic reference JSONs plus database-known names (property,
city, competitors) - deterministic, and explained via matched_rules rather than
a fabricated confidence number.
"""

from sqlalchemy.orm import Session

from app.services.semantic.negation import match_with_negation
from app.services.semantic.text import load_reference, sentences, tokens, find_terms


def _topics_cfg() -> list[dict]:
    return load_reference("semantic_topics.json")["topics"]


def _intents_cfg() -> list[dict]:
    return load_reference("semantic_intents.json")["intents"]


def _normalization_cfg() -> dict:
    return load_reference("semantic_normalization.json")["terms"]


def _entities_cfg() -> dict:
    return load_reference("semantic_entities.json")["entity_types"]


def _sentiment_terms() -> tuple[list[str], list[str]]:
    cfg = load_reference("review_sentiment_terms.json")
    return (
        [t["term"] for t in cfg["positive"]],
        [t["term"] for t in cfg["negative"]],
    )


def property_entity_names(db: Session, property_id: int) -> dict[str, list[str]]:
    """Database-known named entities for a property: its own name, city, and
    tracked competitor names/aliases. Only names the operator entered - nothing
    inferred."""
    from app.models import Competitor, Property

    prop = db.get(Property, property_id)
    if prop is None:
        return {}
    out: dict[str, list[str]] = {}
    if prop.name:
        out["property_name"] = [prop.name]
    if prop.city:
        out["city"] = [prop.city]
    competitors: list[str] = []
    for c in db.query(Competitor).filter_by(property_id=property_id).all():
        competitors.append(c.name)
        competitors.extend(c.aliases or [])
    if competitors:
        out["competitor"] = competitors
    return out


def _clauses(text: str) -> list[str]:
    """Sentences further split at clause breakers ('but', 'however'...), so
    'the pool is amazing but maintenance never came' scores the two topics
    from their own clauses."""
    breakers = set(load_reference("semantic_negation.json")["clause_breakers"])
    out = []
    for sentence in sentences(text):
        toks = tokens(sentence)
        clause: list[str] = []
        for t in toks:
            if t in breakers:
                if clause:
                    out.append(" ".join(clause))
                clause = []
            else:
                clause.append(t)
        if clause:
            out.append(" ".join(clause))
    return out


def _topic_sentiment(text: str, topic_terms: list[str]) -> str:
    """Clause-level per-topic sentiment: in each clause that mentions the
    topic, count global sentiment terms (positive terms negation-aware, so
    'not helpful' votes negative)."""
    pos_terms, neg_terms = _sentiment_terms()
    pos = neg = 0
    for clause in _clauses(text):
        toks = tokens(clause)
        if not toks or not find_terms(toks, topic_terms):
            continue
        p = match_with_negation(clause, pos_terms, positive=True)
        n = match_with_negation(clause, neg_terms)
        pos += len(p.clean)
        neg += len(n.clean) + len(p.flipped)
    if pos and neg:
        return "positive" if pos > neg else "negative" if neg > pos else "mixed"
    if pos:
        return "positive"
    if neg:
        return "negative"
    return "neutral"


def enrich_text(
    text: str, extra_entities: dict[str, list[str]] | None = None
) -> dict:
    """Structured, deterministic metadata for one document/chunk.

    extra_entities maps entity type -> known names (e.g. from
    property_entity_names) merged with the static entity vocabularies.
    """
    rules: list[str] = []

    topics: list[str] = []
    topics_excluded: list[str] = []
    sentiment_by_topic: dict[str, str] = {}
    for topic in _topics_cfg():
        res = match_with_negation(text, topic["terms"])
        if res.clean:
            topics.append(topic["key"])
            rules.extend(f"topic:{topic['key']} term '{t}'" for t in res.clean)
            sentiment_by_topic[topic["key"]] = _topic_sentiment(text, topic["terms"])
        elif res.excluded:
            topics_excluded.append(topic["key"])
        rules.extend(res.rules)

    entity_vocab: dict[str, list[str]] = {k: list(v) for k, v in _entities_cfg().items()}
    for etype, names in (extra_entities or {}).items():
        entity_vocab.setdefault(etype, []).extend(names)
    entities: list[dict] = []
    for etype in sorted(entity_vocab):
        res = match_with_negation(text, entity_vocab[etype])
        for value in res.clean:
            entities.append({"type": etype, "value": value})
            rules.append(f"entity:{etype} '{value}'")

    intents: list[str] = []
    for intent in _intents_cfg():
        res = match_with_negation(text, intent["terms"], positive=True)
        if res.clean:  # a negated cue ("would not recommend") does not assert the intent
            intents.append(intent["key"])
            rules.extend(f"intent:{intent['key']} term '{t}'" for t in res.clean)

    normalized: list[str] = []
    for canonical, variants in _normalization_cfg().items():
        res = match_with_negation(text, variants)
        if res.clean or res.flipped:
            normalized.append(canonical)

    return {
        "topics": topics,
        "topics_excluded": topics_excluded,
        "sentiment_by_topic": sentiment_by_topic,
        "entities": entities,
        "intents": intents,
        "normalized_terms": sorted(normalized),
        "matched_rules": rules,
        "taxonomy_version": load_reference("semantic_topics.json")["version"],
    }
