"""Phase 18A: AI Share of Voice calculation engine. Property Mentions /
(Property + Competitor Mentions), sample-gated, alias-aware, filterable, with
explicit tie handling in competitive rank - and never a fabricated number
when data is missing."""

from datetime import datetime, timezone

import pytest

from app.connectors.base import AIVisibilityQueryProvider
from app.models import AITopic, AIVisibilityPrompt, Competitor, Mention, Property
from app.services.ai_visibility import run_query
from app.services.ai_visibility.mentions import backfill_mentions, persist_mentions_for_query
from app.services.reporting_share_of_voice import (
    build_sov_report,
    competitive_ranking,
    sov_kpi_card,
)


class FR(AIVisibilityQueryProvider):
    def __init__(self, response):
        self.response = response

    def execute_query(self, prompt, platform):
        return self.response

    def get_queries(self, db, property_id):
        return []


# Fixed anchor so `now` (passed into run_query) and `today` (passed into the
# report builders) always agree - relying on wall-clock defaults on both
# sides risks an off-by-one-day window at the UTC/local boundary.
NOW = datetime(2026, 8, 10, 12, 0, tzinfo=timezone.utc)
TODAY = NOW.date()


def _prop(db, name="SoV Court", aliases=None):
    p = Property(name=name, slug=name.lower().replace(" ", "-"), aliases=aliases)
    db.add(p)
    db.commit()
    return p


def _run(db, prop, text, platform="chatgpt", prompt_text="How is the property?", now=None):
    now = now or NOW
    return run_query(db, prop.id, prompt_text, platform, provider=FR(text), now=now)


def test_basic_sov_property_leads(db):
    p = _prop(db)
    comp = Competitor(property_id=p.id, name="Rival Co")
    db.add(comp)
    db.commit()

    _run(db, p, "SoV Court has a pool.")
    _run(db, p, "SoV Court is great.")
    _run(db, p, "Rival Co is fine too.")

    report = build_sov_report(db, p.id, days=30, today=TODAY)
    assert report["overview"]["share_of_voice"] == pytest.approx(2 / 3, rel=1e-3)
    assert report["overview"]["sufficient"] is True
    assert report["overview"]["rank"] == 1
    assert report["overview"]["rank_of"] == 2


def test_multi_competitor_sov(db):
    p = _prop(db)
    c1 = Competitor(property_id=p.id, name="Alpha Co")
    c2 = Competitor(property_id=p.id, name="Beta Co")
    db.add_all([c1, c2])
    db.commit()

    _run(db, p, "SoV Court is nice.")
    _run(db, p, "Alpha Co is nice.")
    _run(db, p, "Alpha Co is the best.")
    _run(db, p, "Beta Co exists too.")

    ranking = competitive_ranking(db, p.id, days=30, today=TODAY)
    by_name = {e["name"]: e for e in ranking["entities"]}
    # property=1/4, Alpha=2/4, Beta=1/4 -> Alpha leads outright; property and
    # Beta are tied for second (both 0.25), matching the tie-handling test.
    assert by_name["Alpha Co"]["share_of_voice"] == pytest.approx(0.5, rel=1e-3)
    assert by_name["Alpha Co"]["rank"] == 1
    assert by_name["SoV Court"]["share_of_voice"] == pytest.approx(0.25, rel=1e-3)
    assert by_name["Beta Co"]["share_of_voice"] == pytest.approx(0.25, rel=1e-3)
    assert by_name["SoV Court"]["rank"] == 2
    assert by_name["Beta Co"]["rank"] == 2


def test_zero_mentions_returns_none_not_zero(db):
    p = _prop(db)
    comp = Competitor(property_id=p.id, name="Rival Co")
    db.add(comp)
    db.commit()

    # Three eligible (sufficient sample) responses, but neither the property
    # nor the competitor is actually mentioned in any of them.
    for _ in range(3):
        _run(db, p, "The weather today is sunny with a chance of rain.")

    report = build_sov_report(db, p.id, days=30, today=TODAY)
    assert report["overview"]["sufficient"] is True
    assert report["overview"]["total_mentions"] == 0
    assert report["overview"]["share_of_voice"] is None


def test_no_eligible_responses_yields_message_not_zero(db):
    p = _prop(db)
    comp = Competitor(property_id=p.id, name="Rival Co")
    db.add(comp)
    db.commit()

    report = build_sov_report(db, p.id, days=30, today=TODAY)
    assert report["overview"]["sample_size"] == 0
    assert report["overview"]["sufficient"] is False
    assert report["overview"]["share_of_voice"] is None


def test_no_competitors_yields_explicit_message(db):
    p = _prop(db)
    report = build_sov_report(db, p.id, days=30, today=TODAY)
    assert report["has_competitors"] is False
    assert "competitors" in report["message"].lower()


def test_rank_ties_share_the_same_rank(db):
    p = _prop(db)
    c1 = Competitor(property_id=p.id, name="Tie Co")
    db.add(c1)
    db.commit()

    # Property and competitor each mentioned once -> equal 50/50 share.
    _run(db, p, "SoV Court is here.")
    _run(db, p, "Tie Co is here.")
    _run(db, p, "Neither one mentioned in this response.")

    ranking = competitive_ranking(db, p.id, days=30, today=TODAY)
    ranks = {e["name"]: e["rank"] for e in ranking["entities"]}
    assert ranks["SoV Court"] == 1
    assert ranks["Tie Co"] == 1


def test_filter_by_platform(db):
    p = _prop(db)
    comp = Competitor(property_id=p.id, name="Rival Co")
    db.add(comp)
    db.commit()

    _run(db, p, "SoV Court on ChatGPT.", platform="chatgpt")
    _run(db, p, "SoV Court on ChatGPT again.", platform="chatgpt")
    _run(db, p, "Rival Co on Gemini.", platform="gemini")

    report = build_sov_report(db, p.id, days=30, platform="chatgpt", today=TODAY)
    assert report["overview"]["sample_size"] == 2
    assert report["overview"]["property_mentions"] == 2
    assert report["overview"]["competitor_mentions"] == 0


def test_filter_by_topic_and_prompt(db):
    p = _prop(db)
    comp = Competitor(property_id=p.id, name="Rival Co")
    db.add(comp)
    db.commit()
    topic = AITopic(property_id=p.id, topic_name="Pricing")
    db.add(topic)
    db.commit()
    prompt = AIVisibilityPrompt(
        property_id=p.id, prompt_text="What is the price?", platform="chatgpt",
        topic_id=topic.id, audience="renters", location_market="Denver",
        intent="pricing", priority="high",
    )
    db.add(prompt)
    db.commit()

    _run(db, p, "SoV Court pricing is fair.", prompt_text="What is the price?")
    _run(db, p, "SoV Court pricing is fair again.", prompt_text="What is the price?")
    _run(db, p, "SoV Court amenities are great.", prompt_text="What amenities exist?")

    by_topic = build_sov_report(db, p.id, days=30, topic_id=topic.id, today=TODAY)
    assert by_topic["overview"]["sample_size"] == 2

    by_prompt = build_sov_report(db, p.id, days=30, prompt_id=prompt.id, today=TODAY)
    assert by_prompt["overview"]["sample_size"] == 2

    for filt in {"audience": "renters", "location": "Denver", "intent": "pricing", "priority": "high"}.items():
        kwargs = {filt[0]: filt[1]}
        r = build_sov_report(db, p.id, days=30, today=TODAY, **kwargs)
        assert r["overview"]["sample_size"] == 2, filt


def test_filter_by_competitor_excludes_other_competitors(db):
    p = _prop(db)
    c1 = Competitor(property_id=p.id, name="Alpha Co")
    c2 = Competitor(property_id=p.id, name="Beta Co")
    db.add_all([c1, c2])
    db.commit()

    _run(db, p, "SoV Court is nice.")
    _run(db, p, "Alpha Co is nice.")
    _run(db, p, "Beta Co is nice.")

    report = build_sov_report(db, p.id, days=30, competitor_id=c1.id, today=TODAY)
    # total should only include property + Alpha Co, not Beta Co.
    assert report["overview"]["total_mentions"] == 2
    assert report["overview"]["competitor_mentions"] == 1


def test_alias_mention_attributed_and_not_double_counted(db):
    p = _prop(db, aliases=["The SoV Court Apartments"])
    comp = Competitor(property_id=p.id, name="Rival Co", aliases=["Rival"])
    db.add(comp)
    db.commit()

    # Response uses the alias form, not the canonical name.
    q = _run(db, p, "The SoV Court Apartments has great amenities, unlike Rival.")

    mentions = db.query(Mention).filter_by(response_id=q.id).all()
    prop_mentions = [m for m in mentions if m.entity_type == "property"]
    assert len(prop_mentions) == 1  # presence-counted, not one row per word
    assert prop_mentions[0].raw_matched_text == "The SoV Court Apartments"
    assert prop_mentions[0].normalized_name == "SoV Court"

    comp_mentions = [m for m in mentions if m.entity_type == "competitor"]
    assert len(comp_mentions) == 1
    assert comp_mentions[0].raw_matched_text == "Rival"


def test_backfill_mentions_is_idempotent(db):
    p = _prop(db)
    comp = Competitor(property_id=p.id, name="Rival Co")
    db.add(comp)
    db.commit()

    q = _run(db, p, "SoV Court beats Rival Co.")
    # Simulate pre-feature history: wipe the auto-persisted mentions.
    db.query(Mention).filter_by(response_id=q.id).delete()
    db.commit()
    assert db.query(Mention).filter_by(response_id=q.id).count() == 0

    out1 = backfill_mentions(db, property_id=p.id)
    assert out1["queries_processed"] == 1
    assert db.query(Mention).filter_by(response_id=q.id).count() == 2

    # Re-running does not duplicate rows.
    out2 = backfill_mentions(db, property_id=p.id)
    assert out2["queries_processed"] == 1
    assert db.query(Mention).filter_by(response_id=q.id).count() == 2


def test_kpi_card_percentage_point_comparison(db):
    p = _prop(db)
    comp = Competitor(property_id=p.id, name="Rival Co")
    db.add(comp)
    db.commit()

    from app.services.reporting_share_of_voice import _window
    import datetime as dt

    today = dt.date(2026, 8, 10)
    prev_day = today - dt.timedelta(days=31)

    # Previous window: property mentioned in 1 of 4 -> 25% share.
    for _ in range(3):
        _run(db, p, "Rival Co only.", now=datetime.combine(prev_day, dt.time(12, 0), tzinfo=timezone.utc))
    _run(db, p, "SoV Court mentioned.", now=datetime.combine(prev_day, dt.time(13, 0), tzinfo=timezone.utc))

    # Current window: property mentioned in 3 of 4 -> 75% share.
    for _ in range(3):
        _run(db, p, "SoV Court is great.", now=datetime.combine(today, dt.time(12, 0), tzinfo=timezone.utc))
    _run(db, p, "Rival Co exists.", now=datetime.combine(today, dt.time(13, 0), tzinfo=timezone.utc))

    kpi = sov_kpi_card(db, p.id, days=30, today=today)
    assert kpi["share_of_voice"] == pytest.approx(0.75, rel=1e-3)
    # 75% - 25% = +50 points, NOT a +200% relative change.
    assert kpi["comparison"]["point_change"] == pytest.approx(0.50, rel=1e-3)
    assert kpi["comparison"]["direction"] == "up"
