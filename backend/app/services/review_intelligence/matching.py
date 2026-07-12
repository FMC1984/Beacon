"""Text normalization, whole-word/phrase matching, and knowledge-base loaders.

Normalization: lowercase, replace every non-alphanumeric character with a space,
collapse whitespace. Both the review text and the KB terms are normalized the
same way, then a term matches if its space-padded normalized form is a substring
of the space-padded normalized text. That yields case-insensitive whole-word and
whole-phrase matching (so "bar" does not match "barn", and "move-in" == "move
in"). These low-level matchers are LITERAL; since Phase 15a the analyzer runs
its term lists through the shared semantic negation layer
(app/services/semantic), so "not very clean" counts as a cleanliness complaint
and "did not have a maintenance issue" is not a maintenance mention.
"""

import json
import re
from functools import lru_cache
from pathlib import Path

REFERENCE_DIR = Path(__file__).resolve().parent.parent.parent / "reference_data"
_NON_ALNUM = re.compile(r"[^a-z0-9]+")


def normalize(text: str) -> str:
    return _NON_ALNUM.sub(" ", (text or "").lower()).strip()


def _padded(text: str) -> str:
    return " " + normalize(text) + " "


def matched_terms(text: str, terms) -> list[str]:
    """Terms (in the order given) whose normalized phrase appears in text."""
    padded = _padded(text)
    out = []
    for t in terms:
        if (" " + normalize(t) + " ") in padded:
            out.append(t)
    return out


def has_any(text: str, terms) -> bool:
    padded = _padded(text)
    return any((" " + normalize(t) + " ") in padded for t in terms)


@lru_cache(maxsize=8)
def _load(name: str) -> dict:
    return json.loads((REFERENCE_DIR / name).read_text())


def review_themes() -> list[dict]:
    return _load("review_themes.json")["themes"]


def sentiment_terms() -> dict:
    return _load("review_sentiment_terms.json")


def operational_config() -> dict:
    return _load("review_operational_categories.json")


def marketing_themes() -> dict:
    return _load("review_marketing_themes.json")
