"""Phase 19 (7): Gemini, Claude and Perplexity connectors, dormant without
keys. Parsing uses recorded-shape fake payloads only (no network): citations
and retrieval queries come from the provider payload, Gemini redirect links
take the reported source domain, refusals and non-browsing answers are never
stored as evidence, and a platform goes live only when its key is set."""

from types import SimpleNamespace as NS

import httpx
import pytest

from app.config import settings
from app.connectors.base import ProviderResult
from app.services.ai_visibility.providers import (
    BrowsingUnavailableError,
    PlatformNotConnectedError,
    get_ai_visibility_provider,
)
from app.services.ai_visibility.providers_anthropic import (
    ClaudeVisibilityProvider,
    ProviderRefusalError,
    parse_anthropic_message,
)
from app.services.ai_visibility.providers_gemini import GeminiVisibilityProvider, parse_gemini_response
from app.services.ai_visibility.providers_perplexity import parse_perplexity_response
from app.services.ai_visibility.reference import is_live_platform, platform_capabilities
from app.services.observatory.citations import extract_citations
from app.services.observatory.observe import classify_error

GEMINI_BODY = {
    "candidates": [{
        "content": {"parts": [{"text": "Alpha Flats in Lone Tree allows dogs."}]},
        "groundingMetadata": {
            "webSearchQueries": ["pet friendly apartments lone tree co"],
            "groundingChunks": [
                {"web": {"uri": "https://vertexaisearch.cloud.google.com/grounding-api-redirect/abc", "title": "apartments.com"}},
                {"web": {"uri": "https://www.alphaflats.com/pets", "title": "Alpha Flats Pets"}},
            ],
            "groundingSupports": [{"segment": {"startIndex": 0, "endIndex": 36}, "groundingChunkIndices": [0, 1]}],
        },
    }],
    "usageMetadata": {"promptTokenCount": 12, "candidatesTokenCount": 30, "thoughtsTokenCount": 5},
    "modelVersion": "gemini-2.5-flash",
    "responseId": "resp-1",
}


def test_platforms_stay_dormant_without_keys(monkeypatch):
    monkeypatch.setattr(settings, "demo_mode", False)
    for attr in ("gemini_api_key", "anthropic_api_key", "perplexity_api_key"):
        monkeypatch.setattr(settings, attr, "")
    assert is_live_platform("chatgpt")
    for platform, setting in (("gemini", "BEACON_GEMINI_API_KEY"), ("claude", "BEACON_ANTHROPIC_API_KEY"),
                              ("perplexity", "BEACON_PERPLEXITY_API_KEY")):
        assert not is_live_platform(platform)
        assert platform_capabilities(platform)["key_setting"] == setting
        with pytest.raises(PlatformNotConnectedError, match=setting):
            get_ai_visibility_provider(platform)
    with pytest.raises(PlatformNotConnectedError):
        get_ai_visibility_provider("copilot")

    monkeypatch.setattr(settings, "gemini_api_key", "test-key")
    assert is_live_platform("gemini") and platform_capabilities("gemini")["live"]
    assert isinstance(get_ai_visibility_provider("gemini"), GeminiVisibilityProvider)
    monkeypatch.setattr(settings, "demo_mode", True)
    assert not is_live_platform("gemini")  # demo mode never marks a keyed connector live


def test_gemini_parse_and_redirect_domains():
    r = parse_gemini_response(GEMINI_BODY, platform="gemini", requested_model="gemini-2.5-flash", latency_ms=10)
    assert r.search_queries == ("pet friendly apartments lone tree co",)
    assert r.browsed and r.search_operations == 1
    assert r.usage.input_tokens == 12 and r.usage.reasoning_tokens == 5 and r.provider_response_id == "resp-1"
    assert [c.capture_method for c in r.citations] == ["grounding_chunk", "grounding_chunk"]
    assert r.citations[0].start_index == 0 and r.citations[0].end_index == 36
    drafts = extract_citations(r, r.text)
    assert [d.domain for d in drafts] == ["apartments.com", "alphaflats.com"]
    assert drafts[0].url.startswith("https://vertexaisearch")  # the link itself is kept as reported


def test_gemini_provider_discards_ungrounded_answer(monkeypatch):
    monkeypatch.setattr(settings, "demo_mode", False)
    monkeypatch.setattr(settings, "gemini_api_key", "k")
    body = {"candidates": [{"content": {"parts": [{"text": "From memory."}]}}], "usageMetadata": {"promptTokenCount": 3}}
    transport = httpx.MockTransport(lambda req: httpx.Response(200, json=body))
    provider = GeminiVisibilityProvider("k", http=httpx.Client(transport=transport))
    with pytest.raises(BrowsingUnavailableError) as exc:
        provider.execute("q", "gemini")
    assert exc.value.result.usage.input_tokens == 3  # spend still recorded

    limited = httpx.MockTransport(lambda req: httpx.Response(429, json={}))
    with pytest.raises(httpx.HTTPStatusError) as err:
        GeminiVisibilityProvider("k", http=httpx.Client(transport=limited)).execute("q", "gemini")
    assert classify_error(err.value) == "rate_limit"


def _claude_message(stop="end_turn"):
    return {
        "id": "msg_1",
        "model": "claude-opus-5",
        "stop_reason": stop,
        "content": [
            {"type": "server_tool_use", "name": "web_search", "input": {"query": "dog friendly apartments lone tree"}},
            {"type": "web_search_tool_result", "content": [{"type": "web_search_result", "url": "https://rent.com/x", "title": "Rent"}]},
            {"type": "text", "text": "Alpha Flats welcomes dogs.", "citations": [
                {"type": "web_search_result_location", "url": "https://rent.com/x", "title": "Rent", "cited_text": "dogs"}]},
        ],
        "usage": {"input_tokens": 100, "output_tokens": 40, "cache_read_input_tokens": 0,
                  "server_tool_use": {"web_search_requests": 1, "web_fetch_requests": 0}},
    }


def test_claude_parse_citations_queries_and_usage():
    r = parse_anthropic_message(_claude_message(), platform="claude", requested_model="claude-opus-5", latency_ms=5)
    assert r.text == "Alpha Flats welcomes dogs."
    assert r.search_queries == ("dog friendly apartments lone tree",)
    assert [c.url for c in r.citations] == ["https://rent.com/x"]
    assert r.search_operations == 1 and r.browsed and r.usage.output_tokens == 40 and r.model == "claude-opus-5"


class FakeAnthropic:
    def __init__(self, messages):
        self.calls = []
        self._messages = list(messages)
        self.beta = NS(messages=NS(create=self._create))

    def _create(self, **kwargs):
        self.calls.append(kwargs)
        return self._messages.pop(0)


def test_claude_provider_resumes_pause_turn_and_uses_fallbacks(monkeypatch):
    monkeypatch.setattr(settings, "demo_mode", False)
    monkeypatch.setattr(settings, "anthropic_api_key", "k")
    fake = FakeAnthropic([_claude_message("pause_turn"), _claude_message()])
    result = ClaudeVisibilityProvider("k", client=fake).execute("q", "claude", location={"city": "Lone Tree"})
    assert isinstance(result, ProviderResult) and len(fake.calls) == 2
    first = fake.calls[0]
    assert first["tools"][0]["type"] == "web_search_20260209"
    assert first["tools"][0]["user_location"] == {"type": "approximate", "city": "Lone Tree"}
    assert first["fallbacks"] == "default" and first["betas"] == ["server-side-fallback-2026-07-01"]
    assert fake.calls[1]["messages"][1]["role"] == "assistant"

    refused = FakeAnthropic([{**_claude_message("refusal"), "content": []}])
    with pytest.raises(ProviderRefusalError) as exc:
        ClaudeVisibilityProvider("k", client=refused).execute("q", "claude")
    assert classify_error(exc.value) == "provider_refusal"

    with pytest.raises(PlatformNotConnectedError):
        ClaudeVisibilityProvider("k", client=fake).execute("q", "chatgpt")


def test_perplexity_parse_prefers_search_results_and_never_invents_queries():
    body = {"id": "p1", "model": "sonar", "choices": [{"message": {"content": "Try Alpha Flats."}}],
            "search_results": [{"title": "Zillow", "url": "https://www.zillow.com/lone-tree"}],
            "citations": ["https://www.zillow.com/lone-tree"], "usage": {"prompt_tokens": 9, "completion_tokens": 4}}
    r = parse_perplexity_response(body, platform="perplexity", requested_model="sonar", latency_ms=1)
    assert [(c.url, c.title) for c in r.citations] == [("https://www.zillow.com/lone-tree", "Zillow")]
    assert r.search_queries == () and r.browsed and r.usage.input_tokens == 9
    bare = parse_perplexity_response({"choices": [{"message": {"content": "x"}}]}, platform="perplexity",
                                     requested_model="sonar", latency_ms=1)
    assert bare.citations == () and bare.browsed is None  # unknown, not a false negative


def test_scheduler_rotation_multiplier_for_validation_platforms(db, monkeypatch):
    from app.models import AIPromptCluster, AIRunSchedule, Property
    from app.services.observatory.assignments import assign
    from app.services.observatory.markets import assign_property_market
    from app.services.observatory.prompt_library import PromptDraft, upsert_prompt
    from app.services.observatory.scheduler import sync_schedule

    monkeypatch.setattr(settings, "demo_mode", False)
    monkeypatch.setattr(settings, "gemini_api_key", "k")
    p = Property(name="Rot Place", slug="rot-place", city="Parker", state="CO")
    db.add(p)
    db.commit()
    assign_property_market(db, p)
    prompt, _ = upsert_prompt(db, PromptDraft(text="Best apartments in Parker, CO?", scope="market", topic_key="best_overall",
                                              intent="discovery", importance=5, funnel_stage=None, variant_group="g",
                                              is_representative=True, generated_from={}, market_id=p.market_id))
    c = AIPromptCluster(market_id=p.market_id, scope="market", label="best", importance=5, representative_prompt_id=prompt.id)
    db.add(c)
    db.flush()
    prompt.cluster_id = c.id
    assign(db, cluster_id=c.id, property_id=p.id)
    db.commit()
    sync_schedule(db)
    cadence = {r.platform: r.cadence_days for r in db.query(AIRunSchedule).all()}
    assert cadence == {"chatgpt": 7, "gemini": 28}
