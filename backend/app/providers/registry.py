"""Provider selection. The only place that decides which concrete provider to
use, based on settings. Business logic calls get_*_provider(); it never names a
vendor. To add a provider, implement the interface and extend these factories.
"""

from app.config import settings
from app.providers.base import (
    EmbeddingProvider,
    LLMProvider,
    MissingAPIKeyError,
)
from app.providers.development import DeterministicEmbeddingProvider, DemoLLMProvider
from app.providers.openai_provider import OpenAIEmbeddingProvider, OpenAIProvider

_NO_KEY = (
    "No OpenAI API key configured. Add BEACON_OPENAI_API_KEY to backend/.env, "
    "or set BEACON_DEMO_MODE=1 for keyless demo mode."
)


def get_embedding_provider() -> EmbeddingProvider:
    if settings.demo_mode:
        return DeterministicEmbeddingProvider()
    if not settings.openai_api_key:
        raise MissingAPIKeyError(_NO_KEY)
    return OpenAIEmbeddingProvider(settings.openai_api_key)


def get_llm_provider() -> LLMProvider:
    if settings.demo_mode:
        return DemoLLMProvider()
    if not settings.openai_api_key:
        raise MissingAPIKeyError(_NO_KEY)
    return OpenAIProvider(settings.openai_api_key, settings.nora_model)


def embedding_provider_name() -> str:
    """Provider identity without constructing a client (for the dashboard)."""
    if settings.demo_mode:
        return "deterministic (demo)"
    return "openai" if settings.openai_api_key else "unconfigured"


def llm_provider_name() -> str:
    if settings.demo_mode:
        return "demo (deterministic)"
    return "openai" if settings.openai_api_key else "unconfigured"
