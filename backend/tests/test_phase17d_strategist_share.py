"""Phase 17D: grounded strategist synthesis + tokenized share.

Strategist rules: below the minimum grounded signal the LLM is NEVER called
and a fixed template returns; demo mode is deterministic (no model call);
recommendations that cite no valid fact are dropped in code; citations are
assembled from OUR fact list, never trusted from model output; cap 5.

Share rules: the public route works keyless while every other API path stays
key-protected; tokens are unguessable, rotated on re-share, and revocable;
the shared payload is the frozen snapshot verbatim."""

import json
from datetime import date

import pytest

from app.providers.base import LLMProvider
from app.services.strategist import (
    INSUFFICIENT_TEMPLATE,
    MIN_FACTS_FOR_SYNTHESIS,
    build_strategist,
    _facts,
)
from tests.test_phase17b_story import two_months  # noqa: F401
from tests.test_phase17b_story import _ga4, _gsc, _prop, _upload  # noqa: F401

TODAY = date(2026, 7, 20)


class FakeLLM(LLMProvider):
    """Scripted provider: records calls, returns a fixed payload."""

    name = "fake"

    def __init__(self, payload):
        self.payload = payload
        self.calls = 0

    def generate(self, system, user):
        self.calls += 1
        self.last_system, self.last_user = system, user
        return self.payload

    def stream(self, system, user):  # pragma: no cover - unused
        yield self.payload


def _briefing(db, prop_id, year=2026, month=6):
    from app.services.reporting_briefing import compose_briefing

    return compose_briefing(db, prop_id, year, month, today=TODAY)


# --- gate: no LLM below minimum signal -----------------------------------------


def test_insufficient_signal_never_calls_llm(db):
    p = _prop(db, "Thin Court")
    briefing = _briefing(db, p.id)
    facts = _facts(briefing)
    assert len(facts) < MIN_FACTS_FOR_SYNTHESIS  # a bare property is thin
    llm = FakeLLM("[]")
    out = build_strategist(briefing, llm=llm)
    assert out["state"] == "insufficient_data"
    assert out["message"] == INSUFFICIENT_TEMPLATE
    assert llm.calls == 0  # the LLM was never called


# --- grounding enforced in code --------------------------------------------------


def test_ungrounded_recommendations_are_dropped(db, two_months):
    briefing = _briefing(db, two_months.id)
    facts = _facts(briefing)
    assert len(facts) >= MIN_FACTS_FOR_SYNTHESIS
    payload = json.dumps([
        {"title": "Grounded advice", "why": "w", "impact": "High",
         "effort": "Low", "facts": [1]},
        {"title": "Ungrounded advice", "why": "w", "impact": "High",
         "effort": "Low", "facts": []},
        {"title": "Fact number out of range", "why": "w", "impact": "High",
         "effort": "Low", "facts": [999]},
    ])
    out = build_strategist(briefing, llm=FakeLLM(payload))
    titles = [r["title"] for r in out["recommendations"]]
    assert titles == ["Grounded advice"]
    # Citations come from OUR fact list (text + href), never from the model.
    g = out["recommendations"][0]["grounding"][0]
    assert g["n"] == 1 and g["text"] == facts[0]["text"] and g["href"]


def test_recommendations_capped_at_five(db, two_months):
    briefing = _briefing(db, two_months.id)
    payload = json.dumps([
        {"title": f"Advice {i}", "why": "w", "impact": "Low", "effort": "Low", "facts": [1]}
        for i in range(8)
    ])
    out = build_strategist(briefing, llm=FakeLLM(payload))
    assert len(out["recommendations"]) == 5


def test_unparseable_output_is_honest_not_fabricated(db, two_months):
    briefing = _briefing(db, two_months.id)
    out = build_strategist(briefing, llm=FakeLLM("I think you should just do better marketing!"))
    assert out["state"] == "no_grounded_output"
    assert out["recommendations"] == []
    assert out["message"]


def test_invalid_impact_effort_values_are_nulled(db, two_months):
    briefing = _briefing(db, two_months.id)
    payload = json.dumps([{"title": "T", "why": "w", "impact": "ENORMOUS",
                           "effort": "Trivial", "facts": [1]}])
    out = build_strategist(briefing, llm=FakeLLM(payload))
    rec = out["recommendations"][0]
    assert rec["impact"] is None and rec["effort"] is None


# --- demo mode: deterministic, keyless -------------------------------------------


def test_demo_mode_is_deterministic_no_model(db, two_months, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "demo_mode", True)
    briefing = _briefing(db, two_months.id)
    a = build_strategist(briefing)
    b = build_strategist(briefing)
    assert a["state"] == "ok" and a["provider"] == "demo (deterministic)"
    assert a["recommendations"] == b["recommendations"]
    for r in a["recommendations"]:
        assert r["grounding"]  # even demo recs are grounded


def test_no_key_is_honest_unavailable(db, two_months, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "demo_mode", False)
    monkeypatch.setattr(settings, "openai_api_key", "")
    briefing = _briefing(db, two_months.id)
    out = build_strategist(briefing)
    assert out["state"] == "unavailable"
    assert out["recommendations"] == []


# --- share ------------------------------------------------------------------------


def _snapshot(client, prop_id):
    gen = client.post(f"/api/briefing/generate?property_id={prop_id}&year=2026&month=6")
    return gen.json()["id"]


def test_share_lifecycle_and_rotation(client, db, two_months):
    sid = _snapshot(client, two_months.id)
    t1 = client.post(f"/api/briefing/{sid}/share").json()["token"]
    assert len(t1) >= 24
    assert client.get(f"/api/briefing/shared/{t1}").status_code == 200

    # Re-sharing rotates the token: the old link dies.
    t2 = client.post(f"/api/briefing/{sid}/share").json()["token"]
    assert t2 != t1
    assert client.get(f"/api/briefing/shared/{t1}").status_code == 404
    assert client.get(f"/api/briefing/shared/{t2}").status_code == 200

    # Revoking kills the live link.
    client.delete(f"/api/briefing/{sid}/share")
    assert client.get(f"/api/briefing/shared/{t2}").status_code == 404


def test_shared_payload_is_the_frozen_snapshot(client, db, two_months):
    sid = _snapshot(client, two_months.id)
    token = client.post(f"/api/briefing/{sid}/share").json()["token"]
    shared = client.get(f"/api/briefing/shared/{token}").json()
    direct = client.get(f"/api/briefing/{sid}").json()
    assert shared["shared"] is True
    assert shared["period"] == direct["period"]
    assert shared["health"] == direct["health"]
    assert shared["story"] == direct["story"]
    # Client-safe: no internal RAG metadata in the shared payload.
    blob = json.dumps(shared).lower()
    for forbidden in ["chroma", "chunk_id", "embedding", "similarity", "latency"]:
        assert forbidden not in blob, forbidden


def test_public_route_keyless_while_rest_stays_keyed(db, two_months, monkeypatch):
    """With an access key configured, the shared route answers without the key
    while any other API path 401s."""
    from fastapi.testclient import TestClient

    from app.config import settings
    from app.db import get_db
    from app.main import app

    def override():
        yield db

    app.dependency_overrides[get_db] = override
    try:
        client = TestClient(app)
        sid = client.post(
            f"/api/briefing/generate?property_id={two_months.id}&year=2026&month=6"
        ).json()["id"]
        token = client.post(f"/api/briefing/{sid}/share").json()["token"]

        monkeypatch.setattr(settings, "access_key", "sekret")
        # Keyless: public share works, everything else is locked.
        assert client.get(f"/api/briefing/shared/{token}").status_code == 200
        assert client.get("/api/companies").status_code == 401
        assert client.get(f"/api/briefing/{sid}").status_code == 401
        # POST/DELETE on share stay key-protected even under /briefing.
        assert client.post(f"/api/briefing/{sid}/share").status_code == 401
        assert client.delete(f"/api/briefing/{sid}/share").status_code == 401
    finally:
        app.dependency_overrides.clear()


def test_bad_or_short_tokens_404(client):
    assert client.get("/api/briefing/shared/short").status_code == 404
    assert client.get("/api/briefing/shared/definitely-not-a-real-token-xyz").status_code == 404
