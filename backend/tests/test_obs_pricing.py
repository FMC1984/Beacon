"""Phase 19 (1a): cost is MODELED from provider usage and a configurable rate
table, and UNAVAILABLE (None) whenever no rate exists. Never guessed."""

import json

import pytest

from app.config import settings
from app.connectors.base import ProviderUsage
from app.services.observatory.pricing import cost_label, estimate_cost, load_pricing


def test_shipped_rates_are_null_so_cost_is_unavailable():
    cost, version = estimate_cost(
        "openai", "gpt-5-mini", ProviderUsage(input_tokens=1000, output_tokens=500), 2
    )
    assert cost is None
    assert version.startswith("2026")
    assert cost_label(cost) == "UNAVAILABLE"


def test_unknown_model_is_unavailable_not_zero():
    cost, _ = estimate_cost("openai", "some-new-model", ProviderUsage(input_tokens=10), 0)
    assert cost is None


def test_demo_model_is_priced_at_zero_and_labeled_modeled():
    cost, _ = estimate_cost("demo", "demo", ProviderUsage(input_tokens=0, output_tokens=0), 1)
    assert cost == 0.0
    assert cost_label(cost) == "MODELED"


def test_override_rates_produce_a_cost(monkeypatch):
    monkeypatch.setattr(
        settings,
        "ai_pricing_overrides_json",
        json.dumps({
            "version": "test-2026-09",
            "models": {
                "openai:gpt-5-mini": {
                    "input_per_1m": 1.0, "cached_input_per_1m": 0.5,
                    "output_per_1m": 2.0, "search_call_per_1k": 10.0,
                }
            },
        }),
    )
    assert load_pricing()["version"] == "test-2026-09"
    usage = ProviderUsage(input_tokens=1000, output_tokens=500, reasoning_tokens=0, cached_tokens=200)
    cost, version = estimate_cost("openai", "gpt-5-mini", usage, 2)
    # 800 billable input @1/1M + 200 cached @0.5/1M + 500 output @2/1M + 2 searches @10/1k
    expected = 800 * 1.0 / 1e6 + 200 * 0.5 / 1e6 + 500 * 2.0 / 1e6 + 2 * 10.0 / 1000
    assert cost == pytest.approx(expected, rel=1e-6)
    assert version == "test-2026-09"


def test_malformed_override_is_ignored(monkeypatch):
    monkeypatch.setattr(settings, "ai_pricing_overrides_json", "{not json")
    cost, _ = estimate_cost("openai", "gpt-5-mini", ProviderUsage(input_tokens=10), 0)
    assert cost is None
