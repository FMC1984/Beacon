"""Deterministic source-category classification for the GEO source landscape
(Phase 16D).

A cited domain is classified against operator-anchored facts first (the
property's own website, configured competitor domains), then against known
public-category patterns (government, directory, review platform, media). A
domain that matches nothing stays 'unknown' - Beacon never guesses a category,
the same posture competitors and property context already take.
"""

import json
from functools import lru_cache
from pathlib import Path

_REF = Path(__file__).resolve().parent.parent / "reference_data" / "source_categories.json"

# Categories in the order they win when several could apply. Owned and
# competitor are operator-anchored and always take precedence.
OWNED = "owned"
COMPETITOR = "competitor"
GOVERNMENT = "government"
DIRECTORY = "directory"
REVIEW_PLATFORM = "review_platform"
MEDIA = "media"
UNKNOWN = "unknown"

CATEGORY_LABELS = {
    OWNED: "Owned",
    COMPETITOR: "Competitor",
    GOVERNMENT: "Government",
    DIRECTORY: "Directory",
    REVIEW_PLATFORM: "Review platform",
    MEDIA: "Media",
    UNKNOWN: "Unknown",
}


@lru_cache(maxsize=1)
def _patterns() -> dict:
    with open(_REF) as fh:
        return json.load(fh)


def _norm(domain: str | None) -> str | None:
    if not domain:
        return None
    d = domain.strip().lower()
    d = d.split("/", 1)[0].split("?", 1)[0].split("#", 1)[0]
    return d[4:] if d.startswith("www.") else d or None


def _host_matches(host: str, entry: str) -> bool:
    """Exact host or a subdomain of entry (host == entry or endswith '.'+entry).
    So 'apartments.com' matches 'www.apartments.com' and 'de.apartments.com',
    but never a lookalike like 'notapartments.com'."""
    return host == entry or host.endswith("." + entry)


def _suffix_matches(host: str, suffix: str) -> bool:
    return host == suffix or host.endswith("." + suffix)


def classify_domain(
    domain: str,
    owned_domains: set[str],
    competitor_domains: set[str],
) -> str:
    host = _norm(domain)
    if host is None:
        return UNKNOWN
    if any(_host_matches(host, d) for d in owned_domains if d):
        return OWNED
    if any(_host_matches(host, d) for d in competitor_domains if d):
        return COMPETITOR
    pats = _patterns()
    for suffix in pats.get("government", {}).get("suffixes", []):
        if _suffix_matches(host, suffix):
            return GOVERNMENT
    if any(_host_matches(host, d) for d in pats.get("government", {}).get("domains", [])):
        return GOVERNMENT
    for category, key in (
        (DIRECTORY, "directory"),
        (REVIEW_PLATFORM, "review_platform"),
        (MEDIA, "media"),
    ):
        if any(_host_matches(host, d) for d in pats.get(key, {}).get("domains", [])):
            return category
    return UNKNOWN
