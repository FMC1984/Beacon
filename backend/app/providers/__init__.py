"""Provider abstraction: Beacon is provider-agnostic for both generation and
embeddings. Business logic depends only on the LLMProvider / EmbeddingProvider
interfaces in `base`; concrete providers are selected by `registry` from
settings. Add a new provider by implementing the interface and wiring it into
the registry; no business logic changes."""

from app.providers.base import (
    EmbeddingProvider,
    LLMProvider,
    MissingAPIKeyError,
)
from app.providers.registry import (
    embedding_provider_name,
    get_embedding_provider,
    get_llm_provider,
    llm_provider_name,
)

__all__ = [
    "EmbeddingProvider",
    "LLMProvider",
    "MissingAPIKeyError",
    "get_embedding_provider",
    "get_llm_provider",
    "embedding_provider_name",
    "llm_provider_name",
]
