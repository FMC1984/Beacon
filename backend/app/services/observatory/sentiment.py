"""Mention sentiment (Phase 19, slice 3). MODELED, rule-based: the clause-
level lexicon sentiment the semantic layer already applies to review
themes, evaluated on the text window around the mention with the entity's
own names as the topic terms. No model calls."""

from app.services.semantic.enrichment import _topic_sentiment

WINDOW_CHARS = 240
SCORES = {"positive": 1.0, "mixed": 0.0, "neutral": 0.0, "negative": -1.0}


def mention_sentiment(text: str, position: int | None, terms: list[str]) -> tuple[str, float, str]:
    """(label, score, excerpt). Neutral when nothing around the mention
    carries sentiment; never inferred from tone Beacon cannot see."""
    if position is None:
        return "neutral", 0.0, ""
    start = max(0, position - WINDOW_CHARS)
    window = (text or "")[start: position + WINDOW_CHARS]
    label = _topic_sentiment(window, [t.lower() for t in terms if t])
    excerpt = " ".join(window.split())
    return label, SCORES.get(label, 0.0), excerpt[:500]
