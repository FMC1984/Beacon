"""Provider interfaces.

Two seams, both pluggable without touching business logic:

- EmbeddingProvider: turns text into vectors. Carries a `name` (vendor) and a
  `version` (model/algorithm) so the RAG registry can record exactly which
  provider produced each embedding, and the sync service can force a full
  rebuild when either changes. `key` (name:version) identifies the vector
  space; a changed key means existing vectors are not comparable.
- LLMProvider: generates text. `generate` returns a full string; `stream`
  yields incremental text so a future streaming UI needs no interface change.

Future providers (Gemini, Claude, Cohere embeddings, a local model) implement
these and register in `registry`. Nothing else in Beacon changes.
"""

from abc import ABC, abstractmethod
from collections.abc import Iterator


class MissingAPIKeyError(RuntimeError):
    """Raised when a network-backed provider is requested without credentials."""


class EmbeddingProvider(ABC):
    #: vendor/family, e.g. "openai", "deterministic"
    name: str = "base"
    #: model or algorithm version, e.g. "text-embedding-3-small", "v1"
    version: str = "0"

    @abstractmethod
    def embed(self, texts: list[str]) -> list[list[float]]:
        """Return one vector per input text, in order."""

    @abstractmethod
    def dimension(self) -> int:
        """Vector length this provider produces."""

    @property
    def key(self) -> str:
        """Identifies the vector space. A changed key invalidates stored
        vectors (different provider or model), forcing a full re-embed."""
        return f"{self.name}:{self.version}"


class LLMProvider(ABC):
    #: vendor/family, e.g. "openai", "demo"
    name: str = "base"

    @abstractmethod
    def generate(self, system: str, user: str) -> str:
        """Return the complete generated answer."""

    @abstractmethod
    def stream(self, system: str, user: str) -> Iterator[str]:
        """Yield the answer incrementally as text fragments."""
