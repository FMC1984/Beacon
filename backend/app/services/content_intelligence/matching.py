"""Term matching + knowledge-base loaders for Content Intelligence.

Matching is whole-token (word-boundary) and case-insensitive, so "bar" does not
match "barn". Multi-word terms match as phrases. This is intentionally simple
and deterministic: the whole engine is reproducible from these rules.
"""

import json
import re
from functools import lru_cache
from pathlib import Path

REFERENCE_DIR = Path(__file__).resolve().parent.parent.parent / "reference_data"


@lru_cache(maxsize=256)
def _pattern(term: str) -> re.Pattern:
    return re.compile(r"(?<!\w)" + re.escape(term.lower()) + r"(?!\w)")


def matched_terms(text: str, terms: tuple[str, ...] | list[str]) -> list[str]:
    """Return the terms that appear in text, in the order given."""
    lowered = text.lower()
    return [t for t in terms if _pattern(t).search(lowered)]


def has_any(text: str, terms) -> bool:
    lowered = text.lower()
    return any(_pattern(t).search(lowered) for t in terms)


@lru_cache(maxsize=8)
def _load(name: str) -> dict:
    return json.loads((REFERENCE_DIR / name).read_text())


def _kb_file(kind: str, property_type: str) -> str:
    """Which KB file a property type uses; defaults to the multifamily file."""
    from app.services.property_types import type_config

    ci = type_config(property_type).get("content_intelligence", {})
    fallback = {
        "renter_questions": "renter_questions.json",
        "content_intent": "content_intent.json",
    }
    return ci.get(kind, fallback[kind])


def renter_questions(property_type: str = "multifamily_apartment") -> list[dict]:
    return _load(_kb_file("renter_questions", property_type))["questions"]


def neighborhood_config() -> dict:
    return _load("neighborhood_topics.json")


def content_intent(property_type: str = "multifamily_apartment") -> dict:
    return _load(_kb_file("content_intent", property_type))
