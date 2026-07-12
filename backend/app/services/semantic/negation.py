"""Deterministic negation handling (Phase 15a).

Fixes the documented literal-matching limitation ("not very clean" counting as
praise for "very clean") with conservative, rule-listed behavior from
semantic_negation.json:

- A plain cue ("not", "never", "wasn't"...) shortly before a POSITIVE term
  flips it to negative evidence. Plain cues never touch negative or topic
  terms: "never fixed my broken heater" must stay a maintenance complaint.
- An absence phrase ("did not have", "never had"...) shortly before any term
  excludes the mention entirely.
- Bare "no"/"zero"/"without" excludes only inside a problem-noun span ("no
  maintenance issues"), so "no parking" stays a complaint.
- A cue inside the matched term itself never negates it (KB phrases like
  "not fixed" are already-negated complaints).
- Clause breakers ("but", "however"...) end a cue's scope; "not only"/"not
  just" are not negations.

Anything outside these rules is left as a literal match - missed negations are
acceptable, invented ones are not.
"""

from dataclasses import dataclass, field

from app.services.semantic.text import find_phrase, find_terms, load_reference, sentences, tokens


def _cfg() -> dict:
    return load_reference("semantic_negation.json")


@dataclass
class MatchSets:
    """Unique terms from negation-aware matching, by how they matched.

    clean: matched with no applicable negation.
    flipped: positive-list terms preceded by a plain negation cue (count these
        as negative evidence).
    excluded: terms negated by an absence phrase or problem-noun span (drop).
    rules: human-readable strings explaining every flip/exclusion.
    """

    clean: list[str] = field(default_factory=list)
    flipped: list[str] = field(default_factory=list)
    excluded: list[str] = field(default_factory=list)
    rules: list[str] = field(default_factory=list)


def _phrase_positions(toks: list[str], phrases) -> list[tuple[int, int]]:
    """(start, end_exclusive) for every occurrence of every phrase."""
    spans = []
    for p in phrases:
        pt = tokens(p)
        for s in find_phrase(toks, pt):
            spans.append((s, s + len(pt)))
    return spans


def _blocked(toks: list[str], cue_end: int, match_start: int, breakers) -> bool:
    return any(t in breakers for t in toks[cue_end:match_start])


def _cue_excepted(toks: list[str], cue_end: int, exceptions) -> bool:
    return cue_end < len(toks) and toks[cue_end] in exceptions


def _within(cue_end: int, match_start: int, window: int) -> bool:
    intervening = match_start - cue_end
    return 0 <= intervening <= window


def _overlaps(a_start: int, a_end: int, b_start: int, b_end: int) -> bool:
    return a_start < b_end and b_start < a_end


def _problem_spans(toks: list[str], cfg) -> list[tuple[int, int]]:
    """Spans from a problem-span cue to a problem noun ('no ... issues')."""
    nouns = set(cfg["problem_nouns"])
    window = cfg["problem_span_window_tokens"]
    spans = []
    for i, t in enumerate(toks):
        if t not in cfg["problem_span_cues"]:
            continue
        for j in range(i + 1, min(i + 1 + window + 1, len(toks))):
            if toks[j] in nouns:
                spans.append((i, j + 1))
                break
    return spans


def match_with_negation(text: str, terms, positive: bool = False) -> MatchSets:
    """Negation-aware whole-word/phrase matching over each sentence.

    positive=True enables plain-cue flipping (only positive term lists flip);
    absence phrases and problem-noun spans apply to every list. Each term is
    reported once, with exclusion taking precedence over flipping and any
    clean occurrence of a term outranking its negated occurrences (one
    non-negated mention means the concept was genuinely discussed).
    """
    cfg = _cfg()
    breakers = set(cfg["clause_breakers"])
    state: dict[str, str] = {}  # term -> clean | flipped | excluded
    rules: list[str] = []

    for sentence in sentences(text):
        toks = tokens(sentence)
        if not toks:
            continue
        matches = find_terms(toks, terms)
        if not matches:
            continue
        cues = _phrase_positions(toks, cfg["cues"])
        absences = _phrase_positions(toks, cfg["absence_phrases"])
        problems = _problem_spans(toks, cfg)

        for term, m_start, m_end in matches:
            verdict = "clean"

            def applicable(c_start, c_end):
                if _overlaps(c_start, c_end, m_start, m_end):
                    return False  # cue is part of the matched term
                return not _blocked(toks, c_end, m_start, breakers)

            for a_start, a_end in absences:
                if applicable(a_start, a_end) and _within(
                    a_end, m_start, cfg["absence_window_tokens"]
                ):
                    verdict = "excluded"
                    rules.append(
                        f"exclude '{term}': absence phrase "
                        f"'{' '.join(toks[a_start:a_end])}'"
                    )
                    break
            if verdict == "clean":
                for p_start, p_end in problems:
                    if _overlaps(p_start, p_end, m_start, m_end) and not _overlaps(
                        p_start, p_start + 1, m_start, m_end
                    ):
                        verdict = "excluded"
                        rules.append(
                            f"exclude '{term}': problem span "
                            f"'{' '.join(toks[p_start:p_end])}'"
                        )
                        break
            if verdict == "clean" and positive:
                for c_start, c_end in cues:
                    if (
                        applicable(c_start, c_end)
                        and _within(c_end, m_start, cfg["flip_window_tokens"])
                        and not _cue_excepted(
                            toks, c_end, cfg["cue_exceptions_following"]
                        )
                    ):
                        verdict = "flipped"
                        rules.append(
                            f"flip '{term}': negation cue '{toks[c_start:c_end][0] if c_end - c_start == 1 else ' '.join(toks[c_start:c_end])}'"
                        )
                        break

            # A clean occurrence anywhere outranks negated occurrences.
            prev = state.get(term)
            if prev == "clean" or verdict == "clean":
                state[term] = "clean"
            elif prev is None or verdict == "excluded" and prev == "flipped":
                state[term] = verdict

    result = MatchSets(rules=rules)
    for term in terms:  # preserve KB order, one entry per term
        if term in state:
            getattr(result, {"clean": "clean", "flipped": "flipped", "excluded": "excluded"}[state[term]]).append(term)
    return result
