"""OpenAI implementations of the provider interfaces.

Embeddings use the embeddings endpoint (text-embedding-3-small, 1536 dims);
generation uses the Responses API. The Responses API does not produce embedding
vectors, so the two live in separate providers by design.
"""

from collections.abc import Iterator

from app.providers.base import EmbeddingProvider, LLMProvider

EMBEDDING_MODEL = "text-embedding-3-small"
EMBEDDING_DIMENSION = 1536


class OpenAIEmbeddingProvider(EmbeddingProvider):
    name = "openai"

    def __init__(self, api_key: str, model: str = EMBEDDING_MODEL):
        from openai import OpenAI

        self._client = OpenAI(api_key=api_key)
        self.version = model

    def embed(self, texts: list[str]) -> list[list[float]]:
        response = self._client.embeddings.create(model=self.version, input=texts)
        return [item.embedding for item in response.data]

    def dimension(self) -> int:
        return EMBEDDING_DIMENSION


class OpenAIProvider(LLMProvider):
    name = "openai"

    def __init__(self, api_key: str, model: str):
        from openai import OpenAI

        self._client = OpenAI(api_key=api_key)
        self.model = model

    def generate(self, system: str, user: str) -> str:
        response = self._client.responses.create(
            model=self.model, instructions=system, input=user
        )
        return response.output_text

    def stream(self, system: str, user: str) -> Iterator[str]:
        stream = self._client.responses.create(
            model=self.model, instructions=system, input=user, stream=True
        )
        for event in stream:
            delta = getattr(event, "delta", None)
            if isinstance(delta, str):
                yield delta
