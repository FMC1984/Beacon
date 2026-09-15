"""Claude connector for AI Visibility (Phase 19, slice 7). Dormant until
BEACON_ANTHROPIC_API_KEY is set: without a key the platform is not live and
no request is ever made.

Uses the official Anthropic SDK with the server-side web search tool, so an
answer carries what Claude actually retrieved:
  server_tool_use (name "web_search")  -> OBSERVED retrieval queries
  text block citations (web_search_result_location) -> provider citations
  web_search_tool_result blocks        -> sources consulted (browsed signal)
  usage.server_tool_use.web_search_requests -> search operations
A refusal is surfaced as an error, never stored as an empty answer. The
server-side `fallbacks: "default"` option re-runs a declined request on
Anthropic's recommended fallback model inside the same call.
"""

import time

from app.config import settings
from app.connectors.base import ProviderCitation, ProviderResult, ProviderUsage
from app.services.ai_visibility.providers import (
    BrowsingUnavailableError,
    PlatformNotConnectedError,
    _StoredReader,
)
from app.services.ai_visibility.reference import is_live_platform, platform_config, platform_label

WEB_SEARCH_TOOL = "web_search_20260209"
FALLBACK_BETA = "server-side-fallback-2026-07-01"
MAX_PAUSE_CONTINUATIONS = 3
INSTRUCTIONS = (
    "You are a general AI assistant answering a consumer's question. Answer normally and cite sources where relevant."
)


class ProviderRefusalError(RuntimeError):
    """The provider declined to answer; nothing is stored as evidence."""


def _get(obj, key, default=None):
    if isinstance(obj, dict):
        return obj.get(key, default)
    return getattr(obj, key, default)


def parse_anthropic_message(message, *, platform: str, requested_model: str | None, latency_ms: int | None) -> ProviderResult:
    """Deterministic parse of a Messages API response (SDK object or dict).
    Missing pieces stay empty; nothing is inferred."""
    text_parts: list[str] = []
    citations: list[ProviderCitation] = []
    queries: list[str] = []
    results_seen = 0
    offset = 0
    for block in _get(message, "content", None) or []:
        btype = _get(block, "type")
        if btype == "text":
            chunk = _get(block, "text", "") or ""
            for c in _get(block, "citations", None) or []:
                if _get(c, "type") == "web_search_result_location" and _get(c, "url"):
                    citations.append(ProviderCitation(
                        url=_get(c, "url"), title=_get(c, "title"), start_index=offset,
                        end_index=offset + len(chunk), capture_method="provider_annotation",
                    ))
            text_parts.append(chunk)
            offset += len(chunk)
        elif btype == "server_tool_use" and _get(block, "name") == "web_search":
            q = (_get(block, "input", None) or {}).get("query") if isinstance(_get(block, "input", None), dict) else None
            if q:
                queries.append(q)
        elif btype == "web_search_tool_result":
            content = _get(block, "content", None)
            if isinstance(content, list):  # an error result is an object, not a list
                results_seen += len(content)
    usage = _get(message, "usage", None)
    server = _get(usage, "server_tool_use", None) if usage is not None else None
    searches = int(_get(server, "web_search_requests", 0) or 0) if server is not None else len(queries)
    raw = message.model_dump() if hasattr(message, "model_dump") else message if isinstance(message, dict) else None
    return ProviderResult(
        text="".join(text_parts),
        provider="anthropic",
        platform=platform,
        model=_get(message, "model", None) or requested_model,
        citations=tuple(citations),
        search_queries=tuple(queries),
        usage=ProviderUsage(
            input_tokens=_get(usage, "input_tokens") if usage is not None else None,
            output_tokens=_get(usage, "output_tokens") if usage is not None else None,
            cached_tokens=_get(usage, "cache_read_input_tokens") if usage is not None else None,
        ),
        search_operations=searches,
        browsed=bool(searches or results_seen),
        latency_ms=latency_ms,
        provider_response_id=_get(message, "id", None),
        raw_payload=raw,
    )


class ClaudeVisibilityProvider(_StoredReader):
    name = "anthropic"

    def __init__(self, api_key: str, model: str | None = None, client=None):
        if client is None:
            from anthropic import Anthropic

            client = Anthropic(api_key=api_key)
        self._client = client
        self.model = model or settings.ai_claude_model

    def execute(self, prompt: str, platform: str, *, model=None, location=None) -> ProviderResult:
        if (platform_config(platform) or {}).get("connector") != "anthropic" or not is_live_platform(platform):
            raise PlatformNotConnectedError(f"{platform_label(platform)} is not connected.")
        tool: dict = {"type": WEB_SEARCH_TOOL, "name": "web_search", "max_uses": settings.ai_web_search_max_uses}
        if location:
            tool["user_location"] = {"type": "approximate", **location}
        messages: list = [{"role": "user", "content": prompt}]
        started = time.perf_counter()
        message = None
        for _ in range(MAX_PAUSE_CONTINUATIONS + 1):
            message = self._client.beta.messages.create(
                model=model or self.model,
                max_tokens=settings.ai_claude_max_tokens,
                system=INSTRUCTIONS,
                messages=messages,
                tools=[tool],
                betas=[FALLBACK_BETA],
                fallbacks="default",
            )
            if _get(message, "stop_reason") != "pause_turn":
                break
            # Server-side search loop paused: resend the turn so it resumes.
            messages = [messages[0], {"role": "assistant", "content": _get(message, "content")}]
        latency_ms = int((time.perf_counter() - started) * 1000)
        result = parse_anthropic_message(message, platform=platform, requested_model=model or self.model, latency_ms=latency_ms)
        if _get(message, "stop_reason") == "refusal":
            raise ProviderRefusalError(f"{platform_label(platform)} declined to answer this prompt.")
        if location:
            result = ProviderResult(**{**result.__dict__, "location": location})
        if settings.ai_visibility_require_search and not result.browsed:
            raise BrowsingUnavailableError(
                "Run discarded: the model answered without web search.", result=result,
            )
        return result

    def execute_query(self, prompt: str, platform: str) -> str:
        return self.execute(prompt, platform).text
