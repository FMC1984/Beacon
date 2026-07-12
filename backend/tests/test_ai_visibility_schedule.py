"""AI Visibility standing prompts + scheduled scoring: CRUD, run-all with a
deterministic provider, score-history snapshots (honest None below the sample
gate), budget stop, and type-aware suggestions."""

import pytest

from app.config import settings
from app.connectors.base import AIVisibilityQueryProvider
from app.models import AIVisibilityQuery, AIVisibilityScoreHistory, Property
from app.services.ai_visibility import schedule


class FakeProvider(AIVisibilityQueryProvider):
    """Deterministic canned response that always names the property."""

    def __init__(self, brand="DCHP"):
        self.brand = brand

    def execute_query(self, prompt, platform):
        return f"For housing help, contact {self.brand}. Source: hud.gov."

    def get_queries(self, db, property_id):
        return []


@pytest.fixture()
def ha(db):
    p = Property(
        name="DCHP", slug="dchp", property_type="housing_authority",
        city="Lone Tree", state="CO",
    )
    db.add(p)
    db.commit()
    return p


def test_prompt_crud(client, ha):
    r = client.post(f"/api/ai-visibility/{ha.id}/prompts", json={"prompt_text": "How do I apply?"})
    assert r.status_code == 201
    pid = r.json()["id"]
    listed = client.get(f"/api/ai-visibility/{ha.id}/prompts").json()
    assert len(listed["prompts"]) == 1
    assert "budget" in listed
    assert client.delete(f"/api/ai-visibility/{ha.id}/prompts/{pid}").status_code == 200
    assert client.get(f"/api/ai-visibility/{ha.id}/prompts").json()["prompts"] == []


def test_empty_prompt_rejected(client, ha):
    assert client.post(f"/api/ai-visibility/{ha.id}/prompts", json={"prompt_text": "  "}).status_code == 422


def test_suggestions_are_type_aware_and_filled(client, ha):
    body = client.get(f"/api/ai-visibility/{ha.id}/prompt-suggestions").json()
    joined = " ".join(body["suggestions"]).lower()
    assert "section 8" in joined or "voucher" in joined  # housing-authority set
    assert "lone tree" in joined  # city filled in
    assert "{" not in joined  # no unfilled placeholders


def test_run_standing_executes_and_snapshots(db, ha, monkeypatch):
    for i in range(3):
        db.add(schedule.AIVisibilityPrompt(property_id=ha.id, prompt_text=f"q{i}", platform="chatgpt"))
    db.commit()
    result = schedule.run_standing_prompts(db, ha.id, provider=FakeProvider())
    assert result["prompts_run"] == 3
    # 3 queries clears the sample gate, so a numeric score is stored.
    assert db.query(AIVisibilityQuery).filter_by(property_id=ha.id).count() == 3
    hist = db.query(AIVisibilityScoreHistory).filter_by(property_id=ha.id).all()
    assert len(hist) == 1
    assert hist[0].sample_size == 3
    assert hist[0].score is not None  # brand named in every response


def test_snapshot_below_gate_is_honest_none(db, ha):
    # No queries run: the score point exists but is None with sample 0.
    snap = schedule.snapshot_score(db, ha.id)
    assert snap["score"] is None and snap["sample_size"] == 0


def test_budget_stop_is_honest(db, ha, monkeypatch):
    monkeypatch.setattr(settings, "ai_visibility_daily_limit", 2)
    for i in range(5):
        db.add(schedule.AIVisibilityPrompt(property_id=ha.id, prompt_text=f"q{i}"))
    db.commit()
    result = schedule.run_standing_prompts(db, ha.id, provider=FakeProvider())
    assert result["prompts_run"] == 2 and result["budget_hit"] is True


def test_score_history_endpoint(client, db, ha):
    schedule.snapshot_score(db, ha.id)
    body = client.get(f"/api/ai-visibility/{ha.id}/score-history").json()
    assert len(body["history"]) == 1
    assert body["history"][0]["sample_size"] == 0
