"""Perplexity connector for AI Visibility (Phase 19, slice 7). Dormant until
BEACON_PERPLEXITY_API_KEY is set.

Sonar models always search. The chat completions response lists the sources
it used (`search_results` with titles, else `citations` URLs); Perplexity does
not report the retrieval queries it ran, so those stay empty and the
capability is UNAVAILABLE rather than guessed.
"""

import time

import httpx

from app.config import settings
from app.connectors.base import ProviderCitation, ProviderResult, ProviderUsage
from app.services.ai_visibility.providers import PlatformNotConnectedError, _StoredReader
from app.services.ai_visibility.reference import is_live_platform, platform_config, platform_label

ENDPOINT = "https://api.perplexity.ai/chat/completions"


def parse_perplexity_response(body: dict, *, platform: str, requested_model: str | None, latency_ms: int | None) -> ProviderResult:
    choices = body.get("choices") or []
    text = ((choices[0].get("message") or {}).get("content") or "") if choices else ""
    results = body.get("search_results") or []
    if results:
        cites = [ProviderCitation(url=r["url"], title=r.get("title")) for r in results if r.get("url")]
    else:
        cites = [ProviderCitation(url=u) for u in (body.get("citations") or []) if isinstance(u, str) and u]
    usage = body.get("usage") or {}
    return ProviderResult(
        text=text,
        provider="perplexity",
        platform=platform,
        model=body.get("model") or requested_model,
        citations=tuple(cites),
        search_queries=(),
        usage=ProviderUsage(input_tokens=usage.get("prompt_tokens"), output_tokens=usage.get("completion_tokens")),
        search_operations=int(usage.get("num_search_queries") or (1 if cites else 0)),
        browsed=bool(cites) or None,
        latency_ms=latency_ms,
        provider_response_id=body.get("id"),
        raw_payload=body,
    )


class PerplexityVisibilityProvider(_StoredReader):
    name = "perplexity"

    def __init__(self, api_key: str, model: str | None = None, http: httpx.Client | None = None):
        self._key = api_key
        self.model = model or settings.ai_perplexity_model
        self._http = http or httpx.Client(timeout=60)

    def execute(self, prompt: str, platform: str, *, model=None, location=None) -> ProviderResult:
        if (platform_config(platform) or {}).get("connector") != "perplexity" or not is_live_platform(platform):
            raise PlatformNotConnectedError(f"{platform_label(platform)} is not connected.")
        use = model or self.model
        started = time.perf_counter()
        resp = self._http.post(
            ENDPOINT,
            headers={"Authorization": f"Bearer {self._key}", "Content-Type": "application/json"},
            json={"model": use, "messages": [{"role": "user", "content": prompt}]},
        )
        latency_ms = int((time.perf_counter() - started) * 1000)
        resp.raise_for_status()
        return parse_perplexity_response(resp.json(), platform=platform, requested_model=use, latency_ms=latency_ms)

    def execute_query(self, prompt: str, platform: str) -> str:
        return self.execute(prompt, platform).text
