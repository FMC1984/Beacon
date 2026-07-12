"""Tier 1 AI referral classifier.

The ONLY detection tier Beacon implements (CLAUDE.md hard rule 2): referrer
domain / UTM source matching against reference_data/ai_referrer_domains.json.
No server-log parsing (Tier 2), no behavioral or ML detection (Tier 3).

The JSON file is the single source of truth for platforms and domains; nothing
here hardcodes a domain. Matching follows build-plan section 4:
  1. referrer/source domain exact or subdomain-suffix match
  2. else case-insensitive utm_source / session_source tag match
First platform match wins. Misses are expected and covered by the undercount
disclosure; when in doubt the classifier does not match (undercount-safe).
"""

import json
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path

REFERENCE_PATH = (
    Path(__file__).resolve().parent.parent / "reference_data" / "ai_referrer_domains.json"
)


@dataclass(frozen=True)
class AIPlatform:
    key: str
    label: str
    referrer_domains: tuple[str, ...]
    utm_sources: tuple[str, ...]


def _normalize_host(source: str) -> str:
    """Reduce a session source to a comparable host: lowercase, no scheme,
    no path, no port. Non-URL tags (e.g. 'chatgpt') pass through lowercased."""
    s = source.strip().lower()
    if "://" in s:
        s = s.split("://", 1)[1]
    s = s.split("/", 1)[0].split("?", 1)[0]
    return s.rsplit(":", 1)[0] if ":" in s else s


class AIReferralClassifier:
    def __init__(self, platforms: list[AIPlatform], version: str):
        self.platforms = platforms
        self.version = version

    @classmethod
    def from_reference_file(cls, path: Path = REFERENCE_PATH) -> "AIReferralClassifier":
        raw = json.loads(path.read_text())
        platforms = [
            AIPlatform(
                key=p["key"],
                label=p["label"],
                referrer_domains=tuple(d.lower() for d in p["referrer_domains"]),
                utm_sources=tuple(u.lower() for u in p["utm_sources"]),
            )
            for p in raw["platforms"]
        ]
        return cls(platforms, raw["version"])

    def classify(self, session_source: str | None) -> str | None:
        """Return the platform key for an AI referral source, else None."""
        if not session_source or not session_source.strip():
            return None
        host = _normalize_host(session_source)

        for platform in self.platforms:
            for domain in platform.referrer_domains:
                if host == domain or host.endswith("." + domain):
                    return platform.key
        for platform in self.platforms:
            if host in platform.utm_sources:
                return platform.key
        return None


@lru_cache(maxsize=1)
def get_classifier() -> AIReferralClassifier:
    return AIReferralClassifier.from_reference_file()
