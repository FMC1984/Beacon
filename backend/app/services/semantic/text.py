"""Token-level text utilities for the semantic layer.

Same normalization contract as the module KBs (lowercase, non-alphanumeric to
space, collapse whitespace) so terms behave identically here and in the
existing engines, plus sentence splitting and token-position phrase search,
which negation scoping needs and plain substring matching cannot provide.
"""

import json
import re
from functools import lru_cache
from pathlib import Path

REFERENCE_DIR = Path(__file__).resolve().parent.parent.parent / "reference_data"
_NON_ALNUM = re.compile(r"[^a-z0-9]+")
_SENTENCE_SPLIT = re.compile(r"[.!?;\n]+")


@lru_cache(maxsize=16)
def load_reference(name: str) -> dict:
    return json.loads((REFERENCE_DIR / name).read_text())


def normalize(text: str) -> str:
    return _NON_ALNUM.sub(" ", (text or "").lower()).strip()


def sentences(text: str) -> list[str]:
    """Raw sentences (split before normalization, so punctuation still marks
    boundaries). Empty segments dropped."""
    return [s for s in (_SENTENCE_SPLIT.split(text or "")) if s.strip()]


def tokens(text: str) -> list[str]:
    n = normalize(text)
    return n.split(" ") if n else []


def find_phrase(hay: list[str], phrase_tokens: list[str]) -> list[int]:
    """Start indices of every occurrence of phrase_tokens in hay."""
    if not phrase_tokens or len(phrase_tokens) > len(hay):
        return []
    hits = []
    for i in range(len(hay) - len(phrase_tokens) + 1):
        if hay[i : i + len(phrase_tokens)] == phrase_tokens:
            hits.append(i)
    return hits


def find_terms(sentence_tokens: list[str], terms) -> list[tuple[str, int, int]]:
    """Every (term, start, end) occurrence of each term in the token list.
    `end` is exclusive. Terms are normalized with the same rule as the text."""
    out = []
    for term in terms:
        tt = tokens(term)
        for start in find_phrase(sentence_tokens, tt):
            out.append((term, start, start + len(tt)))
    return out
