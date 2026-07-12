"""Backwards-compatible shim. The generation abstraction moved to app.providers
in Phase 9; this module re-exports the same names. Prefer importing from
app.providers in new code.
"""

from app.providers.base import LLMProvider as NoraLLM
from app.providers.base import MissingAPIKeyError
from app.providers.development import DEMO_PREFIX
from app.providers.development import DemoLLMProvider as DemoLLM
from app.providers.openai_provider import OpenAIProvider as OpenAIResponsesLLM
from app.providers.registry import get_llm_provider as get_llm

__all__ = [
    "NoraLLM",
    "MissingAPIKeyError",
    "DEMO_PREFIX",
    "DemoLLM",
    "OpenAIResponsesLLM",
    "get_llm",
]
