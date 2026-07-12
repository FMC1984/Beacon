"""Provider abstraction: interfaces, deterministic + demo providers, registry
selection, and back-compat with the old embedder/nora_llm import paths."""

import pytest

from app.providers import (
    EmbeddingProvider,
    LLMProvider,
    MissingAPIKeyError,
    embedding_provider_name,
    get_embedding_provider,
    get_llm_provider,
    llm_provider_name,
)
from app.providers.development import DeterministicEmbeddingProvider, DemoLLMProvider


def test_deterministic_embedding_provider_contract():
    p = DeterministicEmbeddingProvider()
    assert isinstance(p, EmbeddingProvider)
    assert p.name == "deterministic"
    assert p.dimension() == 128
    assert p.key == "deterministic:v1"
    vecs = p.embed(["hello world", "hello world"])
    assert len(vecs) == 2 and len(vecs[0]) == 128
    assert vecs[0] == vecs[1]  # deterministic


def test_demo_llm_provider_contract():
    p = DemoLLMProvider()
    assert isinstance(p, LLMProvider)
    user = "[1] (ga4)\nTotal sessions: 5. Key events (conversions): 1."
    full = p.generate("sys", user)
    streamed = "".join(p.stream("sys", user))
    assert full == streamed
    assert "Total sessions: 5" in full


def test_registry_selects_by_settings(monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "demo_mode", True)
    assert isinstance(get_embedding_provider(), DeterministicEmbeddingProvider)
    assert isinstance(get_llm_provider(), DemoLLMProvider)
    assert embedding_provider_name().startswith("deterministic")
    assert llm_provider_name().startswith("demo")


def test_registry_requires_key_when_not_demo(monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "demo_mode", False)
    monkeypatch.setattr(settings, "openai_api_key", "")
    with pytest.raises(MissingAPIKeyError):
        get_embedding_provider()
    with pytest.raises(MissingAPIKeyError):
        get_llm_provider()
    assert embedding_provider_name() == "unconfigured"


def test_openai_providers_construct_without_calling(monkeypatch):
    # Constructing must not hit the network; only embed/generate would.
    from app.providers.openai_provider import (
        EMBEDDING_DIMENSION,
        OpenAIEmbeddingProvider,
        OpenAIProvider,
    )

    emb = OpenAIEmbeddingProvider("sk-test")
    assert emb.name == "openai"
    assert emb.dimension() == EMBEDDING_DIMENSION
    assert emb.version == "text-embedding-3-small"
    llm = OpenAIProvider("sk-test", "gpt-5-mini")
    assert llm.name == "openai" and llm.model == "gpt-5-mini"


def test_backcompat_import_paths():
    # Old imports used across the codebase and tests must still resolve.
    from app.services.rag.embedder import (
        DeterministicEmbedder,
        MissingAPIKeyError as ME,
        get_embedder,
    )
    from app.services.nora_llm import DEMO_PREFIX, DemoLLM, get_llm

    assert DeterministicEmbedder is DeterministicEmbeddingProvider
    assert DemoLLM is DemoLLMProvider
    assert ME is MissingAPIKeyError
    assert "Demo mode" in DEMO_PREFIX
    assert callable(get_embedder) and callable(get_llm)
