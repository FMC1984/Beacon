"""Multifamily topic taxonomy (Phase 19). Loaded from reference JSON so the
vocabulary is a data change, never hardcoded across modules."""

import json
from functools import lru_cache
from pathlib import Path

from app.services.content_intelligence.matching import matched_terms

_REFERENCE = Path(__file__).resolve().parent.parent.parent / "reference_data" / "ai_topic_taxonomy.json"


@lru_cache(maxsize=1)
def taxonomy() -> dict:
    return json.loads(_REFERENCE.read_text())


def topics() -> list[dict]:
    return taxonomy()["topics"]


def topic(key: str) -> dict | None:
    for t in topics():
        if t["key"] == key:
            return t
    return None


def core_topic_keys() -> list[str]:
    return [t["key"] for t in topics() if t.get("core")]


def topics_in_text(text: str) -> list[str]:
    """Taxonomy keys whose terms appear (whole-word) in the text."""
    found = []
    for t in topics():
        if matched_terms(text or "", tuple(t["terms"])):
            found.append(t["key"])
    return found


def topics_for_semantic(semantic_keys: list[str] | None) -> list[str]:
    """Taxonomy keys mapped from semantic-layer topic keys (content tags)."""
    wanted = set(semantic_keys or [])
    return [t["key"] for t in topics() if t.get("semantic_topic") in wanted]
