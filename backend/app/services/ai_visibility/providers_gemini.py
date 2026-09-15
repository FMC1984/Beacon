"""Gemini connector for AI Visibility (Phase 19, slice 7). Dormant until
BEACON_GEMINI_API_KEY is set.

Calls the Gemini API generateContent endpoint with Google Search grounding
over HTTPS (httpx, already a dependency). groundingMetadata supplies:
  webSearchQueries   -> OBSERVED retrieval queries ("Observed Gemini retrieval
                        queries", never consumer search volume)
  groundingChunks    -> provider citations (capture_method grounding_chunk);
                        chunk URIs are Google redirect links, so the source
                        domain comes from the chunk title Gemini reports
  groundingSupports  -> answer offsets for each cited chunk
Gemini bills grounding per grounded prompt, recorded as one search operation.
"""

import time

import httpx

from app.config import settings
from app.connectors.base import ProviderCitation, ProviderResult, ProviderUsage
from app.services.ai_visibility.providers import (
    BrowsingUnavailableError,
    PlatformNotConnectedError,
    _StoredReader,
)
from app.services.ai_visibility.reference import is_live_platform, platform_config, platform_label

ENDPOINT = "https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"


def parse_gemini_response(body: dict, *, platform: str, requested_model: str | None, latency_ms: int | None) -> ProviderResult:
    candidates = body.get("candidates") or []
    cand = candidates[0] if candidates else {}
    parts = ((cand.get("content") or {}).get("parts")) or []
    text = "".join(p.get("text", "") for p in parts if isinstance(p, dict))
    meta = cand.get("groundingMetadata") or {}
    chunks = meta.get("groundingChunks") or []
    offsets: dict[int, tuple[int | None, int | None]] = {}
    for support in meta.get("groundingSupports") or []:
        seg = support.get("segment") or {}
        for idx in support.get("groundingChunkIndices") or []:
            offsets.setdefault(idx, (seg.get("startIndex"), seg.get("endIndex")))
    citations = []
    for i, chunk in enumerate(chunks):
        web = chunk.get("web") or {}
        if not web.get("uri"):
            continue
        start, end = offsets.get(i, (None, None))
        citations.append(ProviderCitation(url=web["uri"], title=web.get("title"), start_index=start, end_index=end,
                                          capture_method="grounding_chunk"))
    queries = tuple(q for q in (meta.get("webSearchQueries") or []) if q)
    usage = body.get("usageMetadata") or {}
    grounded = bool(queries or chunks)
    return ProviderResult(
        text=text,
        provider="gemini",
        platform=platform,
        model=body.get("modelVersion") or requested_model,
        citations=tuple(citations),
        search_queries=queries,
        usage=ProviderUsage(
            input_tokens=usage.get("promptTokenCount"),
            output_tokens=usage.get("candidatesTokenCount"),
            reasoning_tokens=usage.get("thoughtsTokenCount"),
            cached_tokens=usage.get("cachedContentTokenCount"),
        ),
        search_operations=1 if grounded else 0,
        browsed=grounded,
        latency_ms=latency_ms,
        provider_response_id=body.get("responseId"),
        raw_payload=body,
    )


class GeminiVisibilityProvider(_StoredReader):
    name = "gemini"

    def __init__(self, api_key: str, model: str | None = None, http: httpx.Client | None = None):
        self._key = api_key
        self.model = model or settings.ai_gemini_model
        self._http = http or httpx.Client(timeout=60)

    def execute(self, prompt: str, platform: str, *, model=None, location=None) -> ProviderResult:
        if (platform_config(platform) or {}).get("connector") != "gemini" or not is_live_platform(platform):
            raise PlatformNotConnectedError(f"{platform_label(platform)} is not connected.")
        use = model or self.model
        started = time.perf_counter()
        resp = self._http.post(
            ENDPOINT.format(model=use),
            headers={"x-goog-api-key": self._key, "Content-Type": "application/json"},
            json={"contents": [{"role": "user", "parts": [{"text": prompt}]}], "tools": [{"google_search": {}}]},
        )
        latency_ms = int((time.perf_counter() - started) * 1000)
        resp.raise_for_status()
        result = parse_gemini_response(resp.json(), platform=platform, requested_model=use, latency_ms=latency_ms)
        if settings.ai_visibility_require_search and not result.browsed:
            raise BrowsingUnavailableError("Run discarded: the model answered without grounding.", result=result)
        return result

    def execute_query(self, prompt: str, platform: str) -> str:
        return self.execute(prompt, platform).text
