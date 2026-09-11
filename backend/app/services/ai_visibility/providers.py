"""Concrete AIVisibilityQueryProvider implementations + selection.

METHODOLOGY (documented, not implicit): Beacon executes AI Visibility queries by
calling AI-platform APIs directly, NOT by simulating a person in the consumer
chat product. API results can differ from what a real user sees. See
app/reference_data/ai_visibility.json -> query_methodology, which the API echoes
back to callers.

`execute` / `execute_query` are the only non-deterministic operations in
Beacon. `get_queries` is a pure DB read shared by every provider.

Phase 19: `execute` returns a ProviderResult carrying what the provider
actually exposed (citations, retrieval queries, usage, model, raw payload).
Nothing here fills a gap the provider left: a platform whose API reports no
citations yields an empty tuple, and downstream labels it UNAVAILABLE.
"""

import time

from sqlalchemy.orm import Session

from app.config import settings
from app.connectors.base import (
    AIVisibilityQueryProvider,
    AIVisibilityRecord,
    ProviderCitation,
    ProviderResult,
    ProviderUsage,
)
from app.models import AIVisibilityQuery
from app.providers.base import MissingAPIKeyError
from app.services.ai_visibility.reference import is_live_platform, platform_label


class PlatformNotConnectedError(RuntimeError):
    """Recognized platform, but no live connector is implemented for it yet."""


class BrowsingUnavailableError(RuntimeError):
    """require_search is on and the model answered without browsing. The run
    is discarded rather than stored as evidence: a non-browsing response
    measures training recall, not retrieval, and would record a false miss.
    Carries `.result` (the ProviderResult) so the spend is still recorded."""

    def __init__(self, message: str, result: ProviderResult | None = None):
        super().__init__(message)
        self.result = result


def read_queries(db: Session, property_id: int) -> list[AIVisibilityRecord]:
    rows = (
        db.query(AIVisibilityQuery)
        .filter_by(property_id=property_id)
        .order_by(AIVisibilityQuery.executed_at.desc(), AIVisibilityQuery.id.desc())
        .all()
    )
    return [
        AIVisibilityRecord(
            property_id=r.property_id,
            query_id=r.id,
            platform=r.platform,
            prompt_text=r.prompt_text,
            raw_response_text=r.raw_response_text,
            executed_at=r.executed_at,
            brand_mentioned=r.brand_mentioned,
            sources_cited=r.sources_cited or [],
        )
        for r in rows
    ]


class _StoredReader(AIVisibilityQueryProvider):
    """Shares the deterministic read; subclasses implement execute/execute_query."""

    def get_queries(self, db: Session, property_id: int) -> list[AIVisibilityRecord]:
        return read_queries(db, property_id)


class DemoVisibilityProvider(_StoredReader):
    """Deterministic, keyless. Returns a labeled placeholder response derived
    only from the prompt, so demo mode and tests are reproducible and never hit
    an external API. The response echoes the prompt (so a brand named in the
    prompt is 'mentioned') and cites two example domains. The structured
    result carries those two citations and one retrieval query, all labeled
    demo, with zero usage."""

    name = "demo"
    model = "demo"

    _CITATIONS = (
        ("https://www.example.com/apartments", "Example apartments"),
        ("https://apartments.example.org/guide", "Example renter guide"),
    )

    def execute_query(self, prompt: str, platform: str) -> str:
        label = platform_label(platform)
        return (
            f"[Demo mode response - not a live {label} call] "
            f"Regarding: {prompt.strip()}\n"
            "Based on general information, there are several options renters "
            "consider in this area. For details, see "
            "https://www.example.com/apartments and "
            "https://apartments.example.org/guide. "
            "This is a deterministic placeholder; connect a live platform for "
            "real AI-platform responses."
        )

    def execute(self, prompt: str, platform: str, *, model=None, location=None) -> ProviderResult:
        text = self.execute_query(prompt, platform)
        citations = tuple(
            ProviderCitation(
                url=url, title=title, start_index=text.find(url),
                end_index=text.find(url) + len(url), capture_method="demo",
            )
            for url, title in self._CITATIONS
        )
        return ProviderResult(
            text=text,
            provider=self.name,
            platform=platform,
            model=self.model,
            citations=citations,
            search_queries=(f"demo retrieval query: {prompt.strip()[:80]}",),
            usage=ProviderUsage(input_tokens=0, output_tokens=0, reasoning_tokens=0, cached_tokens=0),
            search_operations=1,
            browsed=True,
            latency_ms=0,
            provider_response_id=None,
            raw_payload={"demo": True, "prompt": prompt.strip()},
            location=location,
        )


def _int_or_none(value) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None


def parse_openai_response(response, *, platform: str, provider: str, requested_model: str | None,
                          latency_ms: int | None) -> ProviderResult:
    """Deterministic parse of an OpenAI Responses API object into a
    ProviderResult. Tolerant of partial objects (tests use SimpleNamespace):
    anything missing is None / empty, never invented."""
    output = getattr(response, "output", None) or []
    search_queries: list[str] = []
    citations: list[ProviderCitation] = []
    search_operations = 0
    for item in output:
        item_type = getattr(item, "type", "") or ""
        if item_type == "web_search_call":
            search_operations += 1
            action = getattr(item, "action", None)
            query = getattr(action, "query", None)
            if isinstance(query, str) and query.strip():
                search_queries.append(query.strip())
            queries = getattr(action, "queries", None)
            if isinstance(queries, (list, tuple)):
                search_queries.extend(q.strip() for q in queries if isinstance(q, str) and q.strip())
        elif item_type == "message":
            for content in getattr(item, "content", None) or []:
                for ann in getattr(content, "annotations", None) or []:
                    if (getattr(ann, "type", "") or "") != "url_citation":
                        continue
                    url = getattr(ann, "url", None)
                    if not url:
                        continue
                    citations.append(
                        ProviderCitation(
                            url=url,
                            title=getattr(ann, "title", None),
                            start_index=_int_or_none(getattr(ann, "start_index", None)),
                            end_index=_int_or_none(getattr(ann, "end_index", None)),
                            capture_method="provider_annotation",
                        )
                    )

    usage_obj = getattr(response, "usage", None)
    out_details = getattr(usage_obj, "output_tokens_details", None)
    in_details = getattr(usage_obj, "input_tokens_details", None)
    usage = ProviderUsage(
        input_tokens=_int_or_none(getattr(usage_obj, "input_tokens", None)),
        output_tokens=_int_or_none(getattr(usage_obj, "output_tokens", None)),
        reasoning_tokens=_int_or_none(getattr(out_details, "reasoning_tokens", None)),
        cached_tokens=_int_or_none(getattr(in_details, "cached_tokens", None)),
    )

    raw_payload = None
    dump = getattr(response, "model_dump", None)
    if callable(dump):
        try:
            raw_payload = dump()
        except Exception:  # never let payload capture break a run
            raw_payload = None

    return ProviderResult(
        text=getattr(response, "output_text", "") or "",
        provider=provider,
        platform=platform,
        model=getattr(response, "model", None) or requested_model,
        citations=tuple(citations),
        search_queries=tuple(search_queries),
        usage=usage,
        search_operations=search_operations,
        browsed=search_operations > 0,
        latency_ms=latency_ms,
        provider_response_id=getattr(response, "id", None),
        raw_payload=raw_payload,
    )


class OpenAIVisibilityProvider(_StoredReader):
    """Live, API-based. Queries the ChatGPT connector via the OpenAI Responses
    API. Non-live platforms in the vocabulary raise PlatformNotConnectedError so
    the surface can report them honestly instead of faking a result."""

    name = "openai"

    def __init__(self, api_key: str, model: str):
        from openai import OpenAI

        self._client = OpenAI(api_key=api_key)
        self.model = model

    def execute(self, prompt: str, platform: str, *, model=None, location=None) -> ProviderResult:
        if not is_live_platform(platform):
            raise PlatformNotConnectedError(
                f"No live connector for {platform_label(platform)} yet. Only "
                "platforms marked live in ai_visibility.json can be queried."
            )
        # Neutral instruction: answer the prompt as a general AI assistant would.
        kwargs: dict = {
            "model": model or self.model,
            "instructions": (
                "You are a general AI assistant answering a consumer's question. "
                "Answer normally and cite sources where relevant."
            ),
            "input": prompt,
            "max_output_tokens": settings.ai_visibility_max_output_tokens,
        }
        # Web search: consumer assistants browse for local/volatile questions,
        # so measuring without it records recall, not retrieval.
        if settings.ai_visibility_web_search:
            tool: dict = {"type": "web_search"}
            if location:
                tool["user_location"] = {"type": "approximate", **location}
            kwargs["tools"] = [tool]
        if settings.ai_visibility_reasoning_effort:
            kwargs["reasoning"] = {"effort": settings.ai_visibility_reasoning_effort}

        started = time.perf_counter()
        response = self._client.responses.create(**kwargs)
        latency_ms = int((time.perf_counter() - started) * 1000)

        result = parse_openai_response(
            response, platform=platform, provider=self.name,
            requested_model=model or self.model, latency_ms=latency_ms,
        )
        if location:
            result = ProviderResult(**{**result.__dict__, "location": location})

        if settings.ai_visibility_web_search and settings.ai_visibility_require_search:
            if not result.browsed:
                raise BrowsingUnavailableError(
                    "Run discarded: the model answered without web search. "
                    "Non-browsing responses measure training recall, not "
                    "retrieval, and would record a false miss.",
                    result=result,
                )
        return result

    def execute_query(self, prompt: str, platform: str) -> str:
        return self.execute(prompt, platform).text


def get_ai_visibility_provider(platform: str | None = None) -> AIVisibilityQueryProvider:
    """Provider for a platform. Every live platform routes through OpenAI
    today; `platform` is accepted so later connectors (Gemini, Claude,
    Perplexity) can be selected here without touching callers."""
    if settings.demo_mode:
        return DemoVisibilityProvider()
    if not settings.openai_api_key:
        raise MissingAPIKeyError(
            "No OpenAI API key configured for live AI Visibility queries. Add "
            "BEACON_OPENAI_API_KEY, or set BEACON_DEMO_MODE=1 for keyless demo."
        )
    return OpenAIVisibilityProvider(settings.openai_api_key, settings.ai_visibility_model)


def provider_name() -> str:
    if settings.demo_mode:
        return "demo (deterministic)"
    return "openai (API-based)" if settings.openai_api_key else "unconfigured"
