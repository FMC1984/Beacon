"""Phase 19 (1a): OpenAI Responses API capture. Citations come from
url_citation annotations, retrieval queries from web_search_call actions,
usage from the usage block. Nothing is invented when a field is missing."""

from types import SimpleNamespace

import pytest

from app.config import settings
from app.services.ai_visibility.providers import (
    BrowsingUnavailableError,
    OpenAIVisibilityProvider,
    parse_openai_response,
)


def _fake_response(*, browsed=True, with_annotations=True):
    output = []
    if browsed:
        output.append(
            SimpleNamespace(
                type="web_search_call",
                action=SimpleNamespace(query="best apartments denver pet friendly"),
            )
        )
    annotations = (
        [
            SimpleNamespace(
                type="url_citation", url="https://www.example.com/denver-apartments?utm_source=x",
                title="Denver apartments", start_index=10, end_index=42,
            ),
            SimpleNamespace(
                type="url_citation", url="https://apartments.example.org/guide",
                title="Guide", start_index=50, end_index=80,
            ),
            SimpleNamespace(type="file_citation", url=None),
        ]
        if with_annotations
        else []
    )
    output.append(
        SimpleNamespace(
            type="message",
            content=[SimpleNamespace(type="output_text", text="answer", annotations=annotations)],
        )
    )
    return SimpleNamespace(
        id="resp_123",
        model="gpt-5-mini-2026",
        output=output,
        output_text="An answer citing example.com.",
        usage=SimpleNamespace(
            input_tokens=120,
            output_tokens=80,
            output_tokens_details=SimpleNamespace(reasoning_tokens=30),
            input_tokens_details=SimpleNamespace(cached_tokens=20),
        ),
        model_dump=lambda: {"id": "resp_123", "model": "gpt-5-mini-2026"},
    )


def test_parse_captures_citations_queries_usage_and_raw_payload():
    result = parse_openai_response(
        _fake_response(), platform="chatgpt", provider="openai",
        requested_model="gpt-5-mini", latency_ms=321,
    )
    assert result.model == "gpt-5-mini-2026"  # as reported, not as requested
    assert result.provider_response_id == "resp_123"
    assert result.browsed is True and result.search_operations == 1
    assert result.search_queries == ("best apartments denver pet friendly",)
    assert [c.url for c in result.citations] == [
        "https://www.example.com/denver-apartments?utm_source=x",
        "https://apartments.example.org/guide",
    ]
    assert result.citations[0].start_index == 10 and result.citations[0].end_index == 42
    assert result.citations[0].capture_method == "provider_annotation"
    assert result.usage.input_tokens == 120
    assert result.usage.output_tokens == 80
    assert result.usage.reasoning_tokens == 30
    assert result.usage.cached_tokens == 20
    assert result.raw_payload == {"id": "resp_123", "model": "gpt-5-mini-2026"}
    assert result.latency_ms == 321


def test_parse_never_invents_missing_fields():
    bare = SimpleNamespace(output=[SimpleNamespace(type="message")], output_text="answer from memory")
    result = parse_openai_response(
        bare, platform="chatgpt", provider="openai", requested_model="gpt-5-mini", latency_ms=None
    )
    assert result.citations == ()
    assert result.search_queries == ()
    assert result.browsed is False
    assert result.usage.input_tokens is None
    assert result.raw_payload is None
    assert result.model == "gpt-5-mini"  # requested model is the only thing known


def _provider_with(fake_response):
    provider = OpenAIVisibilityProvider.__new__(OpenAIVisibilityProvider)
    provider.model = "gpt-5-mini"

    class FakeResponses:
        def __init__(self):
            self.kwargs = None

        def create(self, **kwargs):
            self.kwargs = kwargs
            return fake_response

    fake = FakeResponses()
    provider._client = SimpleNamespace(responses=fake)
    return provider, fake


def test_execute_passes_web_search_tool_and_returns_structured_result(monkeypatch):
    monkeypatch.setattr(settings, "ai_visibility_web_search", True)
    monkeypatch.setattr(settings, "ai_visibility_require_search", True)
    provider, fake = _provider_with(_fake_response())
    result = provider.execute("test question", "chatgpt")
    assert any(t["type"] == "web_search" for t in fake.kwargs["tools"])
    assert result.provider == "openai"
    assert len(result.citations) == 2
    assert result.latency_ms is not None and result.latency_ms >= 0
    # Legacy path still returns only the text.
    assert provider.execute_query("test question", "chatgpt") == result.text


def test_non_browsing_run_raises_but_carries_usage_for_cost(monkeypatch):
    monkeypatch.setattr(settings, "ai_visibility_web_search", True)
    monkeypatch.setattr(settings, "ai_visibility_require_search", True)
    provider, _ = _provider_with(_fake_response(browsed=False))
    with pytest.raises(BrowsingUnavailableError) as excinfo:
        provider.execute("test question", "chatgpt")
    assert excinfo.value.result is not None
    assert excinfo.value.result.usage.input_tokens == 120  # the spend is not lost


def test_location_is_forwarded_when_given(monkeypatch):
    monkeypatch.setattr(settings, "ai_visibility_web_search", True)
    monkeypatch.setattr(settings, "ai_visibility_require_search", False)
    provider, fake = _provider_with(_fake_response())
    result = provider.execute("q", "chatgpt", location={"city": "Denver", "region": "Colorado"})
    assert fake.kwargs["tools"][0]["user_location"]["city"] == "Denver"
    assert result.location == {"city": "Denver", "region": "Colorado"}
