"""Backwards-compatible shim. The embedding abstraction moved to app.providers
in Phase 9; this module re-exports the same names so existing imports keep
working. Prefer importing from app.providers in new code.
"""

from app.providers.base import EmbeddingProvider as Embedder
from app.providers.base import MissingAPIKeyError
from app.providers.development import DeterministicEmbeddingProvider as DeterministicEmbedder
from app.providers.openai_provider import EMBEDDING_MODEL
from app.providers.openai_provider import OpenAIEmbeddingProvider as OpenAIEmbedder
from app.providers.registry import get_embedding_provider as get_embedder

__all__ = [
    "Embedder",
    "MissingAPIKeyError",
    "DeterministicEmbedder",
    "OpenAIEmbedder",
    "EMBEDDING_MODEL",
    "get_embedder",
]
