"""Phase 17C: Cross-system insights + strategic questions. The rules under
test: an insight requires observations from 2+ DISTINCT modules (or an action
2+ modules corroborate), the framing is co-occurrence never causation, a
question is generated only when its precondition actually holds and carries
its evidence, and empties are honest."""

from datetime import date, datetime, timezone

import pytest

from app.models import Property, PropertyContent
from app.services.reporting_briefing import (
    CO_OCCURRENCE_NOTE,
    _cross_system,
    _strategic_questions,
    compose_briefing,
)
from tests.test_phase17b_story import _ga4, _gsc, _prop, _upload, two_months  # noqa: F401
from app.models.uploads import SourceType

TODAY = date(2026, 7, 20)
_CAUSAL = ["caused", "because of", "led to", "drove", "resulted in", "thanks to"]


def _item(module, text="x moved"):
    return {
        "text": text,
        "evidence": ["evidence"],
        "link": {"label": "M", "href": "/m"},
        "source_module": module,
    }


# --- cross-system insight rules ------------------------------------------------


def test_co_movement_requires_two_distinct_modules():
    # Two wins from the SAME module: no co-movement insight.
    story = {"wins": [_item("seo"), _item("seo")], "risks": [], "trends": []}
    cs = _cross_system(story, [])
    assert cs["insights"] == []
    assert cs["empty_reason"]

    # Wins from two DIFFERENT modules: one co-movement insight with one
    # observation per module.
    story = {"wins": [_item("seo"), _item("reviews")], "risks": [], "trends": []}
    cs = _cross_system(story, [])
    assert len(cs["insights"]) == 1
    ins = cs["insights"][0]
    assert ins["kind"] == "co_movement"
    assert {o["module"] for o in ins["observations"]} == {"seo", "reviews"}


def test_corroborated_action_requires_two_sources():
    single = {"title": "Do a thing", "supporting_signal_count": 1,
              "source_modules": ["Content IQ"], "explanation": "why"}
    multi = {"title": "Do the corroborated thing", "supporting_signal_count": 2,
             "source_modules": ["Content IQ", "SEO Performance"], "explanation": "why"}
    story = {"wins": [], "risks": [], "trends": []}
    cs = _cross_system(story, [single, multi])
    assert len(cs["insights"]) == 1
    assert cs["insights"][0]["kind"] == "corroborated_action"
    assert "corroborated thing" in cs["insights"][0]["observations"][0]["text"]


def test_insights_never_use_causal_language():
    story = {"wins": [_item("seo"), _item("reviews")], "risks": [_item("ai_visibility"), _item("seo")], "trends": []}
    cs = _cross_system(story, [])
    blob = " ".join(
        (i["title"] + " " + i["framing"] + " " +
         " ".join(o["text"] for o in i["observations"])).lower()
        for i in cs["insights"]
    ) + " " + cs["note"].lower()
    for verb in _CAUSAL:
        assert verb not in blob, verb
    assert "not causation" in cs["note"]
    for i in cs["insights"]:
        assert i["framing"]


def test_insights_capped_at_four():
    story = {"wins": [_item("seo"), _item("reviews")], "risks": [_item("seo"), _item("reviews")], "trends": []}
    actions = [
        {"title": f"a{i}", "supporting_signal_count": 2,
         "source_modules": ["A", "B"], "explanation": "e"}
        for i in range(5)
    ]
    cs = _cross_system(story, actions)
    assert len(cs["insights"]) <= 4


# --- strategic question preconditions --------------------------------------------


def _cards(clicks_dir=None, clicks_state="complete", events_val=5, events_dir="flat",
           geo_state="complete"):
    return {
        "organic_clicks": {
            "state": clicks_state,
            "value": 100,
            "comparison": {"direction": clicks_dir, "previous": 50, "current": 100}
            if clicks_dir else None,
        },
        "organic_key_events": {
            "state": "complete",
            "value": events_val,
            "comparison": {"direction": events_dir, "previous": events_val, "current": events_val},
        },
        "ai_mention_rate": {"state": geo_state},
    }


def test_question_clicks_up_events_flat_only_when_true():
    seo = {"quadrant": {}, "movers": {}}
    review = {}
    story = {"wins": [], "risks": [], "trends": []}
    # Precondition holds: clicks up, events flat.
    qs = _strategic_questions(_cards(clicks_dir="up"), seo, review, story)
    assert any("clicks rise while key events" in q["text"] for q in qs)
    # Precondition absent: clicks flat.
    qs = _strategic_questions(_cards(clicks_dir="flat"), seo, review, story)
    assert not any("clicks rise while key events" in q["text"] for q in qs)


def test_question_striking_distance_counts_named():
    seo = {"quadrant": {"highlights": {"striking_distance": 27}}, "movers": {}}
    qs = _strategic_questions(_cards(), seo, {}, {"wins": [], "risks": [], "trends": []})
    q = next(q for q in qs if "striking-distance" in q["text"])
    assert "27" in q["text"]
    assert q["evidence"]
    assert q["nora_question"]


def test_question_ai_gate_requires_measurable_demand():
    seo = {"quadrant": {}, "movers": {}}
    # Insufficient AI sample + complete clicks -> question generated.
    qs = _strategic_questions(_cards(geo_state="insufficient_sample"), seo, {}, {"wins": [], "risks": [], "trends": []})
    assert any("standing AI Visibility prompts" in q["text"] for q in qs)
    # No clicks data -> no question (nothing measurable to contrast).
    cards = _cards(geo_state="insufficient_sample", clicks_state="not_configured")
    qs = _strategic_questions(cards, seo, {}, {"wins": [], "risks": [], "trends": []})
    assert not any("standing AI Visibility prompts" in q["text"] for q in qs)


def test_questions_capped_and_evidence_backed():
    seo = {
        "quadrant": {"highlights": {"striking_distance": 9}},
        "movers": {"losses": [{"query": "q", "click_change": -8,
                               "previous_clicks": 10, "current_clicks": 2}]},
    }
    review = {"opportunities": [{"theme_label": "Maintenance"}]}
    qs = _strategic_questions(_cards(clicks_dir="up", geo_state="insufficient_sample"),
                              seo, review, {"wins": [], "risks": [], "trends": []})
    assert 1 <= len(qs) <= 5
    for q in qs:
        assert q["why"] and q["evidence"] and q["link"]["href"]
        assert "—" not in q["text"]


# --- composed + frozen -----------------------------------------------------------


def test_briefing_composes_17c_sections(db, two_months):
    b = compose_briefing(db, two_months.id, 2026, 6, today=TODAY)
    assert "cross_system" in b and "strategic_questions" in b
    assert b["cross_system"]["note"] == CO_OCCURRENCE_NOTE
    # two_months has SEO movement only -> co-movement (needs 2 modules) absent,
    # but questions from real preconditions exist (declining query at least).
    assert any("What changed for" in q["text"] for q in b["strategic_questions"])


def test_snapshot_freezes_17c_sections(client, db, two_months):
    gen = client.post(f"/api/briefing/generate?property_id={two_months.id}&year=2026&month=6")
    snap = client.get(f"/api/briefing/{gen.json()['id']}").json()
    assert "cross_system" in snap and "strategic_questions" in snap
