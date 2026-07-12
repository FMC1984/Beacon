"""Concrete AIVisibilityQueryProvider implementations + selection.

METHODOLOGY (documented, not implicit): Beacon executes AI Visibility queries by
calling AI-platform APIs directly, NOT by simulating a person in the consumer
chat product. API results can differ from what a real user sees. See
app/reference_data/ai_visibility.json -> query_methodology, which the API echoes
back to callers.

`execute_query` is the only non-deterministic operation in Beacon. `get_queries`
is a pure DB read shared by every provider.
"""

from sqlalchemy.orm import Session

from app.config import settings
from app.connectors.base import AIVisibilityQueryProvider, AIVisibilityRecord
from app.models import AIVisibilityQuery
from app.providers.base import MissingAPIKeyError
from app.services.ai_visibility.reference import is_live_platform, platform_label


class PlatformNotConnectedError(RuntimeError):
    """Recognized platform, but no live connector is implemented for it yet."""


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
    """Shares the deterministic read; subclasses implement execute_query."""

    def get_queries(self, db: Session, property_id: int) -> list[AIVisibilityRecord]:
        return read_queries(db, property_id)


class DemoVisibilityProvider(_StoredReader):
    """Deterministic, keyless. Returns a labeled placeholder response derived
    only from the prompt, so demo mode and tests are reproducible and never hit
    an external API. The response echoes the prompt (so a brand named in the
    prompt is 'mentioned') and cites two example domains."""

    name = "demo"

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


class OpenAIVisibilityProvider(_StoredReader):
    """Live, API-based. Queries the ChatGPT connector via the OpenAI Responses
    API. Non-live platforms in the vocabulary raise PlatformNotConnectedError so
    the surface can report them honestly instead of faking a result."""

    name = "openai"

    def __init__(self, api_key: str, model: str):
        from openai import OpenAI

        self._client = OpenAI(api_key=api_key)
        self.model = model

    def execute_query(self, prompt: str, platform: str) -> str:
        if not is_live_platform(platform):
            raise PlatformNotConnectedError(
                f"No live connector for {platform_label(platform)} yet. Only "
                "platforms marked live in ai_visibility.json can be queried."
            )
        # Neutral instruction: answer the prompt as a general AI assistant would.
        response = self._client.responses.create(
            model=self.model,
            instructions=(
                "You are a general AI assistant answering a consumer's question. "
                "Answer normally and cite sources where relevant."
            ),
            input=prompt,
        )
        return response.output_text


def get_ai_visibility_provider() -> AIVisibilityQueryProvider:
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
