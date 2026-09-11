"""Provider pricing + per-run cost estimate (Phase 19).

Cost is MODELED: provider-reported token counts and search operations times
a configurable rate table. The shipped table has null rates; until the
operator supplies real prices (reference JSON, BEACON_AI_PRICING_OVERRIDES_JSON
env, or later per-organization settings) every estimate is None and every
surface labels it UNAVAILABLE. Beacon never guesses a dollar figure.
"""

import json
from functools import lru_cache
from pathlib import Path

from app.config import settings
from app.connectors.base import ProviderUsage
from app.services.observatory import LABEL_MODELED, LABEL_UNAVAILABLE

_REFERENCE = (
    Path(__file__).resolve().parent.parent.parent
    / "reference_data"
    / "ai_provider_pricing.json"
)

RATE_KEYS = (
    "input_per_1m",
    "cached_input_per_1m",
    "output_per_1m",
    "search_call_per_1k",
    "grounded_prompt_per_1k",
)


@lru_cache(maxsize=1)
def _reference_pricing() -> dict:
    return json.loads(_REFERENCE.read_text())


def load_pricing() -> dict:
    """Reference table with env overrides merged per model key. Not cached
    because overrides can change between calls (tests, admin edits)."""
    base = json.loads(json.dumps(_reference_pricing()))
    raw = (settings.ai_pricing_overrides_json or "").strip()
    if raw:
        try:
            override = json.loads(raw)
        except json.JSONDecodeError:
            override = {}
        if isinstance(override, dict):
            if override.get("version"):
                base["version"] = str(override["version"])
            for key, rates in (override.get("models") or {}).items():
                if isinstance(rates, dict):
                    base.setdefault("models", {}).setdefault(key, {}).update(rates)
    return base


def model_key(provider: str | None, model: str | None) -> str:
    return f"{provider or 'unknown'}:{model or 'unknown'}"


def estimate_cost(
    provider: str | None,
    model: str | None,
    usage: ProviderUsage,
    search_operations: int = 0,
) -> tuple[float | None, str]:
    """(estimated_cost_usd | None, pricing_version). None when the model has
    no usable rate: an unpriced run is UNAVAILABLE, not free."""
    pricing = load_pricing()
    version = str(pricing.get("version", "unknown"))
    rates = (pricing.get("models") or {}).get(model_key(provider, model))
    if not rates:
        return None, version

    def rate(name: str) -> float | None:
        v = rates.get(name)
        return float(v) if v is not None else None

    input_rate = rate("input_per_1m")
    output_rate = rate("output_per_1m")
    if input_rate is None or output_rate is None:
        return None, version

    input_tokens = usage.input_tokens or 0
    cached = usage.cached_tokens or 0
    billable_input = max(0, input_tokens - cached)
    cached_rate = rate("cached_input_per_1m")
    cached_rate = input_rate if cached_rate is None else cached_rate
    output_tokens = (usage.output_tokens or 0) + (usage.reasoning_tokens or 0)

    cost = (
        billable_input * input_rate / 1_000_000
        + cached * cached_rate / 1_000_000
        + output_tokens * output_rate / 1_000_000
    )
    search_rate = rate("search_call_per_1k")
    if search_rate is not None and search_operations:
        cost += search_operations * search_rate / 1000
    grounded_rate = rate("grounded_prompt_per_1k")
    if grounded_rate is not None and search_operations:
        cost += grounded_rate / 1000
    return round(cost, 6), version


def cost_label(cost: float | None) -> str:
    return LABEL_MODELED if cost is not None else LABEL_UNAVAILABLE
