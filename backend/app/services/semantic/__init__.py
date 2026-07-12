"""Shared Semantic Intelligence layer (Phase 15a).

Deterministic NLP enrichment used by every intelligence module and the RAG
index: topic tagging, entity extraction, intent classification, per-topic
sentiment, phrase normalization, and negation handling. No model calls; every
output is reproducible from the reference JSONs and the input text, and each
assertion carries the matched rule that produced it (never a fabricated
confidence score).
"""

from app.services.semantic.enrichment import (
    enrich_text,
    property_entity_names,
)
from app.services.semantic.negation import MatchSets, match_with_negation

__all__ = [
    "enrich_text",
    "property_entity_names",
    "match_with_negation",
    "MatchSets",
]
