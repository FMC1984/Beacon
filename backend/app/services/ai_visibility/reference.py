"""Loads the AI Visibility vocabulary + methodology from JSON reference data.
Platforms are validated on assignment (vocabulary-in-JSON, no DB enum)."""

import json
from functools import lru_cache
from pathlib import Path

_REFERENCE = (
    Path(__file__).resolve().parent.parent.parent
    / "reference_data"
    / "ai_visibility.json"
)

# A query needs at least this many runs before Beacon will characterize
# visibility; below it, every surface says so (mirrors Phase 11 trend gating).
MIN_QUERIES_FOR_VISIBILITY = 3


@lru_cache(maxsize=1)
def config() -> dict:
    return json.loads(_REFERENCE.read_text())


def platforms() -> list[dict]:
    return config()["platforms"]


def platform_keys() -> list[str]:
    return [p["key"] for p in platforms()]


def platform_label(key: str) -> str:
    for p in platforms():
        if p["key"] == key:
            return p["label"]
    return key


def is_live_platform(key: str) -> bool:
    for p in platforms():
        if p["key"] == key:
            return bool(p.get("live"))
    return False


def platform_config(key: str) -> dict | None:
    for p in platforms():
        if p["key"] == key:
            return p
    return None


def capability_keys() -> list[str]:
    return list(config().get("capability_keys", []))


def platform_capabilities(key: str) -> dict:
    """The capability flags for a platform (Phase 19). Unknown platform or
    missing key reads as False: an unstated capability is UNAVAILABLE, never
    assumed."""
    p = platform_config(key) or {}
    caps = {k: bool(p.get(k, False)) for k in capability_keys()}
    caps["live"] = bool(p.get("live", False))
    caps["connector"] = p.get("connector")
    caps["default_model"] = p.get("default_model")
    return caps


def methodology() -> dict:
    return config()["query_methodology"]


class InvalidPlatformError(ValueError):
    """Platform not in the controlled vocabulary."""


def validate_platform(platform: str) -> str:
    key = (platform or "").strip().lower()
    if key not in platform_keys():
        raise InvalidPlatformError(
            "Unknown AI platform '" + platform + "'. Allowed: "
            + ", ".join(platform_keys())
        )
    return key
