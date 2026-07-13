"""Phase 17B: This Month's Story + Intelligence Cards. The story is a
deterministic derivation from module outputs: every item carries evidence and
a source link, no causal language, empty groups are honest, and gated signals
are excluded rather than zeroed. Intelligence cards give one honest per-module
summary. The snapshot freezes the story with everything else."""

from datetime import date

import pytest

from app.models import GA4SessionsDaily, GSCPerformanceDaily, Property, Upload
from app.models.uploads import SourceType, UploadStatus
from app.services.reporting_briefing import compose_briefing

TODAY = date(2026, 7, 20)
_CAUSAL = ["caused", "because of", "led to", "drove", "resulted in", "thanks to"]


def _prop(db, name="Story Court"):
    p = Property(name=name, slug=name.lower().replace(" ", "-"), city="Denver",
                 state="CO", website_url="https://storycourt.com")
    db.add(p)
    db.commit()
    return p


def _upload(db, pid, source):
    u = Upload(source_type=source, property_id=pid, filename="s.csv",
               status=UploadStatus.PROCESSED, row_count=1)
    db.add(u)
    db.commit()
    return u.id


def _gsc(db, pid, up, d, query, clicks, impressions, position=8.0):
    db.add(GSCPerformanceDaily(property_id=pid, upload_id=up, date=d, query=query,
                               page="/p", clicks=clicks, impressions=impressions,
                               ctr=0.0, position=position))
    db.commit()


def _ga4(db, pid, up, d, sessions, engaged=None, medium="organic"):
    db.add(GA4SessionsDaily(property_id=pid, upload_id=up, date=d,
                            session_source="google", session_medium=medium,
                            sessions=sessions,
                            engaged_sessions=engaged if engaged is not None else sessions,
                            total_users=sessions, key_events=0))
    db.commit()


@pytest.fixture()
def two_months(db):
    """A property with June AND May data so month-over-month movement exists.
    June is clearly better: more clicks on a gaining query, more sessions."""
    p = _prop(db)
    gu = _upload(db, p.id, SourceType.GSC)
    au = _upload(db, p.id, SourceType.GA4)
    # Coverage matters: the truth framework only compares months whose data
    # covers the window (head at day 1, tail within the manual 14-day
    # tolerance). Seed day 1 and day 20+ of BOTH months so the periods are
    # comparable; sparse months are honestly refused (separate test below).
    # May (prior month): modest numbers, impressions above the movers threshold.
    _gsc(db, p.id, gu, date(2026, 5, 1), "apartments denver", 3, 200, position=12.0)
    _gsc(db, p.id, gu, date(2026, 5, 20), "apartments denver", 2, 100, position=12.0)
    _gsc(db, p.id, gu, date(2026, 5, 1), "fading query", 15, 200, position=6.0)
    _gsc(db, p.id, gu, date(2026, 5, 20), "fading query", 15, 200, position=6.0)
    _ga4(db, p.id, au, date(2026, 5, 1), 50)
    _ga4(db, p.id, au, date(2026, 5, 20), 50)
    # June (briefing month): "apartments denver" gains, "fading query" declines.
    _gsc(db, p.id, gu, date(2026, 6, 1), "apartments denver", 20, 300, position=7.0)
    _gsc(db, p.id, gu, date(2026, 6, 20), "apartments denver", 20, 200, position=7.0)
    _gsc(db, p.id, gu, date(2026, 6, 1), "fading query", 2, 180, position=9.0)
    _gsc(db, p.id, gu, date(2026, 6, 20), "fading query", 2, 170, position=9.0)
    _ga4(db, p.id, au, date(2026, 6, 1), 125)
    _ga4(db, p.id, au, date(2026, 6, 20), 125)
    return p


# --- story derivation ---------------------------------------------------------


def test_story_wins_and_risks_from_real_movement(db, two_months):
    b = compose_briefing(db, two_months.id, 2026, 6, today=TODAY)
    story = b["story"]
    assert story["wins"], "June improvements should produce wins"
    assert story["risks"], "the declining query should produce a risk"

    win_text = " ".join(w["text"] for w in story["wins"])
    assert "apartments denver" in win_text or "Organic" in win_text
    risk_text = " ".join(r["text"] for r in story["risks"])
    assert "fading query" in risk_text


def test_every_story_item_carries_evidence_and_link(db, two_months):
    story = compose_briefing(db, two_months.id, 2026, 6, today=TODAY)["story"]
    for group in ("wins", "risks", "trends"):
        for item in story[group]:
            assert item["evidence"], item
            assert item["link"]["href"] and item["link"]["label"]
            assert item["source_module"]
            assert "—" not in item["text"]  # no em dashes in copy


def test_story_has_no_causal_language(db, two_months):
    story = compose_briefing(db, two_months.id, 2026, 6, today=TODAY)["story"]
    blob = " ".join(
        i["text"].lower() for g in ("wins", "risks", "trends") for i in story[g]
    )
    for verb in _CAUSAL:
        assert verb not in blob, verb
    # The note explicitly disclaims causation.
    assert "not causal" in story["note"]


def test_story_groups_capped_at_five(db, two_months):
    story = compose_briefing(db, two_months.id, 2026, 6, today=TODAY)["story"]
    for group in ("wins", "risks", "trends"):
        assert len(story[group]) <= 5


def test_story_empty_when_no_comparable_data(db):
    # One month of data only: no movement is measurable, so the story is
    # honestly empty rather than fabricated.
    p = _prop(db, "Single Month Court")
    gu = _upload(db, p.id, SourceType.GSC)
    _gsc(db, p.id, gu, date(2026, 6, 10), "solo query", 10, 300)
    story = compose_briefing(db, p.id, 2026, 6, today=TODAY)["story"]
    assert story["wins"] == []
    assert story["risks"] == []


def test_story_is_deterministic(db, two_months):
    a = compose_briefing(db, two_months.id, 2026, 6, today=TODAY)["story"]
    b = compose_briefing(db, two_months.id, 2026, 6, today=TODAY)["story"]
    assert a == b


# --- intelligence cards ---------------------------------------------------------


def test_intel_cards_cover_modules_with_honest_states(db, two_months):
    cards = compose_briefing(db, two_months.id, 2026, 6, today=TODAY)["intelligence_cards"]
    by = {c["key"]: c for c in cards}
    assert set(by) == {"seo", "ai_visibility", "content", "reviews"}
    assert by["seo"]["state"] == "ok"
    assert "organic clicks" in by["seo"]["what_happened"]
    # No AI queries and no reviews for this property: honest states, with a
    # concrete next step as the opportunity.
    assert by["ai_visibility"]["state"] == "no_data"
    assert by["reviews"]["state"] == "not_connected"
    for c in cards:
        assert c["what_happened"]
        assert c["href"]
        assert "—" not in c["what_happened"]


def test_intel_card_content_carries_top_opportunity(db, two_months):
    from datetime import datetime, timezone

    from app.models import PropertyContent

    db.add(PropertyContent(property_id=two_months.id, page="homepage", title="Home",
                           body="Story Court in Denver. Apply online via portal.",
                           updated_at=datetime(2026, 6, 1, tzinfo=timezone.utc)))
    db.commit()
    cards = compose_briefing(db, two_months.id, 2026, 6, today=TODAY)["intelligence_cards"]
    content = next(c for c in cards if c["key"] == "content")
    assert content["state"] == "ok"
    assert content["biggest_opportunity"]  # Content IQ's top recommendation


# --- snapshot includes the new sections -----------------------------------------


def test_snapshot_freezes_story_and_cards(client, db, two_months):
    gen = client.post(f"/api/briefing/generate?property_id={two_months.id}&year=2026&month=6")
    snap = client.get(f"/api/briefing/{gen.json()['id']}").json()
    assert "story" in snap and "intelligence_cards" in snap
    assert snap["story"]["wins"], "frozen snapshot carries the composed story"
