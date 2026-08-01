"""Question-set import (DCHP seed format): idempotent prompt upsert with
cadence metadata, org-competitor mapping (listing/government domains stay with
the source classifier), cadence-aware due scheduling, require_search discard,
and deterministic must_contain evaluation in the evidence drawer."""

from datetime import datetime, timezone

import pytest

from app.models import AIVisibilityPrompt, Competitor, Property
from app.services.ai_visibility.question_set import (
    evaluate_must_contain,
    import_question_set,
)
from app.services.ai_visibility.schedule import run_due_prompts
from tests.test_phase16d_geo import FR

SEED = {
    "run_config": {"engine": "chatgpt"},
    "scoring": {
        "known_competitors": [
            "douglasco.gov", "chfainfo.com", "hud.gov", "apartments.com",
        ],
    },
    "questions": [
        {
            "id": "w-001", "cadence": "weekly", "runs": 1, "intent": "voucher",
            "question": "Is the housing voucher waiting list open?",
            "owning_url": "/public-notices/", "volatile": True,
            "must_contain": ["current waiting list status", "dated notice"],
            "notes": "volatile",
        },
        {
            "id": "m-001", "cadence": "monthly", "runs": 2, "intent": "entity",
            "question": "What does the partnership do?",
            "owning_url": "/what-we-do/", "volatile": False,
            "must_contain": ["affordable housing"],
        },
    ],
}


def _prop(db, name="Seed Court"):
    p = Property(name=name, slug=name.lower().replace(" ", "-"),
                 website_url="https://seedcourt.org")
    db.add(p)
    db.commit()
    return p


# --- import ------------------------------------------------------------------


def test_import_creates_prompts_with_metadata(db):
    p = _prop(db)
    out = import_question_set(db, p.id, SEED)
    assert out["prompts_created"] == 2
    weekly = (
        db.query(AIVisibilityPrompt)
        .filter_by(property_id=p.id, cadence="weekly")
        .one()
    )
    assert weekly.volatile is True
    assert weekly.owning_url == "/public-notices/"
    assert weekly.must_contain == ["current waiting list status", "dated notice"]
    monthly = (
        db.query(AIVisibilityPrompt)
        .filter_by(property_id=p.id, cadence="monthly")
        .one()
    )
    assert monthly.runs_per_cycle == 2


def test_import_is_idempotent_updates_not_duplicates(db):
    p = _prop(db)
    import_question_set(db, p.id, SEED)
    revised = {**SEED, "questions": [
        {**SEED["questions"][0], "volatile": False, "notes": "calmed down"},
        SEED["questions"][1],
    ]}
    out = import_question_set(db, p.id, revised)
    assert out["prompts_created"] == 0
    assert out["prompts_updated"] == 2
    assert db.query(AIVisibilityPrompt).filter_by(property_id=p.id).count() == 2
    weekly = db.query(AIVisibilityPrompt).filter_by(
        property_id=p.id, cadence="weekly").one()
    assert weekly.volatile is False and weekly.notes == "calmed down"


def test_import_maps_only_org_competitors(db):
    p = _prop(db)
    out = import_question_set(db, p.id, SEED)
    names = {c.name for c in db.query(Competitor).filter_by(property_id=p.id)}
    # douglasco.gov and chfainfo.com are org competitors; hud.gov and
    # apartments.com stay with the source classifier (government/directory).
    assert names == {"Douglas County Government", "CHFA"}
    assert set(out["competitors_created"]) == names
    # Idempotent.
    out2 = import_question_set(db, p.id, SEED)
    assert out2["competitors_created"] == []


def test_import_endpoint_and_validation(client, db):
    p = _prop(db, "Endpoint Court")
    r = client.post(f"/api/ai-visibility/{p.id}/import-question-set", json=SEED)
    assert r.status_code == 200
    assert r.json()["prompts_created"] == 2
    bad = client.post(f"/api/ai-visibility/{p.id}/import-question-set", json={"questions": []})
    assert bad.status_code == 422
    assert client.post("/api/ai-visibility/999/import-question-set", json=SEED).status_code == 404


# --- cadence-aware scheduling --------------------------------------------------


def _now(y, m, d):
    return datetime(y, m, d, 12, 0, tzinfo=timezone.utc)


def test_weekly_due_every_seven_days_monthly_on_1_and_15(db):
    p = _prop(db, "Cadence Court")
    import_question_set(db, p.id, SEED)
    provider = FR("A fine answer citing https://seedcourt.org")

    # Day 10: weekly never ran -> due; monthly not (not the 1st/15th).
    out = run_due_prompts(db, p.id, provider=provider, now=_now(2026, 8, 10))
    assert out["prompts_due"] == 1 and out["prompts_run"] == 1

    # Day 12 (2 days later): weekly not due again yet.
    out = run_due_prompts(db, p.id, provider=provider, now=_now(2026, 8, 12))
    assert out["prompts_due"] == 0

    # Day 15: monthly due (runs_per_cycle=2 -> days 1 and 15); weekly still not.
    out = run_due_prompts(db, p.id, provider=provider, now=_now(2026, 8, 15))
    assert out["prompts_due"] == 1 and out["prompts_run"] == 1

    # Same day again: idempotent, nothing due.
    out = run_due_prompts(db, p.id, provider=provider, now=_now(2026, 8, 15))
    assert out["prompts_due"] == 0

    # Day 17: weekly due again (7 days since day 10).
    out = run_due_prompts(db, p.id, provider=provider, now=_now(2026, 8, 17))
    assert out["prompts_due"] == 1

    # Sept 1: monthly due again (first run day of the new month).
    out = run_due_prompts(db, p.id, provider=provider, now=_now(2026, 9, 1))
    assert out["prompts_due"] >= 1


# --- require_search discard -----------------------------------------------------


def test_non_browsing_run_is_discarded_not_stored(db, monkeypatch):
    """With require_search on, a response produced without web search raises
    and no query row is stored - a recall-only answer would be a false miss."""
    from types import SimpleNamespace

    from app.config import settings
    from app.services.ai_visibility.providers import (
        BrowsingUnavailableError,
        OpenAIVisibilityProvider,
    )

    monkeypatch.setattr(settings, "ai_visibility_web_search", True)
    monkeypatch.setattr(settings, "ai_visibility_require_search", True)

    provider = OpenAIVisibilityProvider.__new__(OpenAIVisibilityProvider)
    provider.model = "test-model"

    class FakeResponses:
        def create(self, **kwargs):
            assert any(t["type"] == "web_search" for t in kwargs.get("tools", []))
            assert kwargs.get("max_output_tokens") == settings.ai_visibility_max_output_tokens
            # No web_search_call item in the output -> the model did not browse.
            return SimpleNamespace(
                output=[SimpleNamespace(type="message")],
                output_text="answer from memory",
            )

    provider._client = SimpleNamespace(responses=FakeResponses())
    with pytest.raises(BrowsingUnavailableError):
        provider.execute_query("test question", "chatgpt")


def test_browsing_run_passes(db, monkeypatch):
    from types import SimpleNamespace

    from app.config import settings
    from app.services.ai_visibility.providers import OpenAIVisibilityProvider

    monkeypatch.setattr(settings, "ai_visibility_web_search", True)
    monkeypatch.setattr(settings, "ai_visibility_require_search", True)

    provider = OpenAIVisibilityProvider.__new__(OpenAIVisibilityProvider)
    provider.model = "test-model"

    class FakeResponses:
        def create(self, **kwargs):
            return SimpleNamespace(
                output=[SimpleNamespace(type="web_search_call"),
                        SimpleNamespace(type="message")],
                output_text="a browsed answer",
            )

    provider._client = SimpleNamespace(responses=FakeResponses())
    assert provider.execute_query("test question", "chatgpt") == "a browsed answer"


# --- must_contain evaluation ----------------------------------------------------


def test_evaluate_must_contain_is_deterministic_containment():
    out = evaluate_must_contain(
        "DCHP maintains a Current Waiting List Status page with a dated notice.",
        ["current waiting list status", "dated notice", "missing thing"],
    )
    assert out == [
        {"component": "current waiting list status", "present": True},
        {"component": "dated notice", "present": True},
        {"component": "missing thing", "present": False},
    ]
    assert evaluate_must_contain("anything", None) == []


def test_evidence_drawer_carries_required_components(db):
    from app.services.ai_visibility import run_query
    from app.services.reporting_geo import matrix_cell_evidence

    p = _prop(db, "Drawer Court")
    import_question_set(db, p.id, SEED)
    q = run_query(
        db, p.id, "Is the housing voucher waiting list open?", "chatgpt",
        provider=FR("The current waiting list status is open per the dated notice."),
        now=_now(2026, 8, 10),
    )
    ev = matrix_cell_evidence(db, p.id, q.id)
    assert ev["volatile"] is True
    assert ev["owning_url"] == "/public-notices/"
    comps = {c["component"]: c["present"] for c in ev["required_components"]}
    assert comps == {"current waiting list status": True, "dated notice": True}
