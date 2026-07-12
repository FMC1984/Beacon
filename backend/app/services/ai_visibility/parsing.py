"""Deterministic parsing of a stored AI response.

Hard rule (Phase 11.5): identical stored text always yields identical parsed
output. No re-querying the AI to "confirm" a parse. Mention detection is the
same literal, case-insensitive, whole-word/phrase, negation-UNAWARE matching
established in Phase 11 - "detected from response text", never a semantic claim
about what the AI meant.
"""

import re

# A brand token must appear as a whole word/phrase (surrounded by non-word
# characters), case-insensitively. Negation-unaware by design (documented): a
# response saying "X is not a good fit" still counts as a mention of X.
_WORD = r"[^\w]"


def _phrase_present(text: str, phrase: str) -> bool:
    phrase = phrase.strip().lower()
    if not phrase:
        return False
    pattern = rf"(?:^|{_WORD}){re.escape(phrase)}(?:{_WORD}|$)"
    return re.search(pattern, text.lower()) is not None


def detect_mention(text: str, brand_terms: list[str]) -> bool:
    """True if any brand term is present as a whole word/phrase. Deterministic."""
    return any(_phrase_present(text, t) for t in brand_terms if t)


# URLs and bare domains. Markdown links, angle brackets, and trailing
# punctuation are all handled so the same response always yields the same set.
_URL_RE = re.compile(r"https?://[^\s)>\]\"']+", re.IGNORECASE)
_BARE_DOMAIN_RE = re.compile(
    r"\b(?:[a-z0-9](?:[a-z0-9-]{0,61}[a-z0-9])?\.)+"
    r"(?:com|org|net|gov|edu|io|co|us|info|biz)\b",
    re.IGNORECASE,
)


def _domain_of(url: str) -> str:
    host = re.sub(r"^https?://", "", url.strip(), flags=re.IGNORECASE)
    host = host.split("/", 1)[0].split("?", 1)[0].split("#", 1)[0]
    host = host.rstrip(".,);]\"'").lower()
    return host[4:] if host.startswith("www.") else host


def extract_sources(text: str) -> list[str]:
    """Deterministically extract cited source domains from a response. Returns a
    sorted, de-duplicated list of hostnames (full URLs are reduced to their
    domain so the same source cited twice counts once)."""
    domains: set[str] = set()
    for url in _URL_RE.findall(text):
        d = _domain_of(url)
        if d:
            domains.add(d)
    for bare in _BARE_DOMAIN_RE.findall(text):
        d = _domain_of(bare)
        if d:
            domains.add(d)
    return sorted(domains)
