"""Phase 19 (1a): the ProviderResult seam. Legacy string providers keep
working through the base shim; the demo provider returns structured,
labeled citations and retrieval queries; normalization is schema-versioned
and the raw payload round-trips through compression."""

from app.connectors.base import AIVisibilityQueryProvider, ProviderResult
from app.services.ai_visibility.providers import DemoVisibilityProvider
from app.services.observatory.provider_result import (
    SCHEMA_VERSION,
    compress_payload,
    decompress_payload,
    normalize_result,
    response_hash,
)


class LegacyStringProvider(AIVisibilityQueryProvider):
    name = "legacy"

    def execute_query(self, prompt, platform):
        return f"answer to {prompt}"

    def get_queries(self, db, property_id):
        return []


def test_base_shim_wraps_string_provider_without_inventing_evidence():
    result = LegacyStringProvider().execute("q", "chatgpt")
    assert isinstance(result, ProviderResult)
    assert result.text == "answer to q"
    assert result.provider == "legacy"
    assert result.citations == ()
    assert result.search_queries == ()
    assert result.browsed is None  # provider cannot say; never assumed
    assert result.usage.input_tokens is None


def test_demo_provider_returns_structured_labeled_result():
    result = DemoVisibilityProvider().execute("best apartments in Denver", "chatgpt")
    assert result.provider == "demo"
    assert len(result.citations) == 2
    assert all(c.capture_method == "demo" for c in result.citations)
    assert result.search_queries and result.search_queries[0].startswith("demo retrieval query")
    assert result.usage.input_tokens == 0 and result.usage.output_tokens == 0
    assert result.browsed is True
    assert "Demo mode response" in result.text
    # execute_query still returns the same text for legacy callers.
    assert DemoVisibilityProvider().execute_query("best apartments in Denver", "chatgpt") == result.text


def test_normalize_result_is_schema_versioned_and_payload_round_trips():
    result = DemoVisibilityProvider().execute("q", "chatgpt")
    normalized = normalize_result(result)
    assert normalized["schema_version"] == SCHEMA_VERSION
    assert normalized["citations"][0]["url"] == result.citations[0].url
    assert normalized["search_queries"] == list(result.search_queries)
    blob = compress_payload(result.raw_payload)
    assert isinstance(blob, bytes)
    assert decompress_payload(blob) == result.raw_payload
    assert compress_payload(None) is None and decompress_payload(None) is None


def test_response_hash_is_deterministic():
    assert response_hash("abc") == response_hash("abc")
    assert response_hash("abc") != response_hash("abd")
    assert len(response_hash("")) == 64
