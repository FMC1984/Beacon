"""Per-platform capability flags + provider selection (Phase 19).

A capability that is False is UNAVAILABLE for that platform: Beacon never
fills the gap with a guess (no synthesized citations, no invented retrieval
queries). Flags live in reference_data/ai_visibility.json so adding a
platform or correcting what its API exposes is a data change.
"""

from dataclasses import dataclass

from app.connectors.base import AIVisibilityQueryProvider
from app.services.ai_visibility.reference import platform_capabilities as _caps


@dataclass(frozen=True)
class Capabilities:
    platform: str
    live: bool
    connector: str | None
    default_model: str | None
    supports_web_search: bool
    supports_search_query_capture: bool
    supports_citation_capture: bool
    supports_source_capture: bool
    supports_location: bool
    supports_model_selection: bool
    supports_raw_response: bool

    def as_dict(self) -> dict:
        return dict(self.__dict__)


def platform_capabilities(platform: str) -> Capabilities:
    c = _caps(platform)
    return Capabilities(
        platform=platform,
        live=c["live"],
        connector=c.get("connector"),
        default_model=c.get("default_model"),
        supports_web_search=c["supports_web_search"],
        supports_search_query_capture=c["supports_search_query_capture"],
        supports_citation_capture=c["supports_citation_capture"],
        supports_source_capture=c["supports_source_capture"],
        supports_location=c["supports_location"],
        supports_model_selection=c["supports_model_selection"],
        supports_raw_response=c["supports_raw_response"],
    )


def provider_for_platform(platform: str) -> AIVisibilityQueryProvider:
    """Today every live platform routes through the configured provider
    (demo, or OpenAI for chatgpt). Later phases map connector -> provider."""
    from app.services.ai_visibility.providers import get_ai_visibility_provider

    return get_ai_visibility_provider(platform)
