"""Recommendation classification, rule v1 (Phase 19, slice 3). MODELED.

A mentioned property counts as "recommended" when the answer either names
it among the first three entities or attaches a recommendation cue to it
in the same sentence, and no cue in that sentence is negated ("would not
recommend"). The sentence bound keeps one entity's verdict from leaking
onto a neighbor named just before it.
Deterministic and inspectable; a later phase can swap in a small model
under a different recommendation_method without touching the ledger.
"""

from app.services.semantic import match_with_negation

METHOD = "rule_v1"
CUES = (
    "recommend", "recommended", "top pick", "top choice", "best choice", "best option",
    "great option", "great choice", "highly rated", "standout", "stands out",
    "worth considering", "consider", "a good fit", "good place to live", "popular choice",
)
RANK_THRESHOLD = 3
WINDOW_CHARS = 160


_BOUNDARIES = ".!?\n"


def _sentence_window(text: str, position: int) -> str:
    """The sentence containing `position`, capped at WINDOW_CHARS each side."""
    lo = max(0, position - WINDOW_CHARS)
    start = max((text.rfind(b, lo, position) for b in _BOUNDARIES), default=-1) + 1
    hi = min(len(text), position + WINDOW_CHARS)
    ends = [i for i in (text.find(b, position, hi) for b in _BOUNDARIES) if i != -1]
    end = min(ends) + 1 if ends else hi
    return text[max(start, lo):end]


def classify_recommendation(
    text: str, *, mentioned: bool, mention_position: int | None, mention_rank: int | None
) -> tuple[bool | None, str, list[str]]:
    """(recommended, method, rules). None when the property is not mentioned."""
    if not mentioned or mention_position is None:
        return None, METHOD, []
    rules: list[str] = []
    if mention_rank is not None and mention_rank <= RANK_THRESHOLD:
        rules.append(f"rank {mention_rank} <= {RANK_THRESHOLD}")
    window = _sentence_window(text or "", mention_position)
    res = match_with_negation(window, list(CUES), positive=True)
    if res.clean:
        rules.append("cue " + ", ".join(sorted(set(res.clean))))
    if res.flipped:
        rules.append("negated cue " + ", ".join(sorted(set(res.flipped))))
        return False, METHOD, rules
    return (bool(rules), METHOD, rules)
