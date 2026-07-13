"""Phase 17A: Monthly Strategic Briefing. The synthesis layer over existing
modules. Load-bearing rules: no opaque composite health score (health is a
COUNT of healthy modules); every module status is explainable and honest
(not-enough-data / not-connected rather than a fabricated band); snapshots are
frozen; the month window threads cleanly through the reused engines."""

from datetime import date, datetime, timezone

import pytest

from app.models import (
    GA4SessionsDaily,
    GSCPerformanceDaily,
    Property,
    PropertyContent,
    Upload,
)
from app.models.uploads import SourceType, UploadStatus
from app.services.reporting_briefing import (
    NOT_CONNECTED,
    NOT_ENOUGH_DATA,
    STATUS_LABELS,
    _band,
    _latest_data_month,
    _month_bounds,
    _prev_month,
    compose_briefing,
)
from app.services.reporting_executive import build_executive_report

TODAY = date(2026, 7, 20)


def _prop(db, name="Briefing Court"):
    p = Property(name=name, slug=name.lower().replace(" ", "-"), city="Denver", state="CO",
                 website_url="https://briefingcourt.com")
    db.add(p)
    db.commit()
    return p


def _upload(db, pid, source):
    u = Upload(source_type=source, property_id=pid, filename="s.csv",
               status=UploadStatus.PROCESSED, row_count=1)
    db.add(u)
    db.commit()
    return u.id


def _gsc(db, pid, up, d, clicks, impressions):
    db.add(GSCPerformanceDaily(property_id=pid, upload_id=up, date=d, query="q", page="/p",
                               clicks=clicks, impressions=impressions, ctr=0.0, position=8.0))
    db.commit()


def _ga4(db, pid, up, d, sessions, engaged, medium="organic"):
    db.add(GA4SessionsDaily(property_id=pid, upload_id=up, date=d, session_source="google",
                            session_medium=medium, sessions=sessions, engaged_sessions=engaged,
                            total_users=sessions, key_events=0))
    db.commit()


def _content(db, pid):
    db.add(PropertyContent(property_id=pid, page="homepage", title="Homepage",
                           body="Briefing Court in Denver offers apartments. Apply online via the portal.",
                           updated_at=datetime(2026, 6, 15, tzinfo=timezone.utc)))
    db.commit()


# --- month helpers -----------------------------------------------------------


def test_month_bounds_and_prev():
    assert _month_bounds(2026, 6) == (date(2026, 6, 1), date(2026, 6, 30))
    assert _month_bounds(2026, 2) == (date(2026, 2, 1), date(2026, 2, 28))
    assert _prev_month(2026, 1) == (2025, 12)
    assert _prev_month(2026, 7) == (2026, 6)


def test_band_thresholds():
    assert _band(90) == "excellent"
    assert _band(72) == "good"
    assert _band(60) == "fair"
    assert _band(30) == "needs_attention"


def test_latest_data_month_prefers_gsc(db):
    p = _prop(db)
    gu = _upload(db, p.id, SourceType.GSC)
    au = _upload(db, p.id, SourceType.GA4)
    _gsc(db, p.id, gu, date(2026, 6, 20), 5, 100)   # GSC newest: June
    _ga4(db, p.id, au, date(2026, 7, 3), 10, 5)     # GA4 newest: July (partial)
    # Default month is the newest complete SEO month (June), not partial July.
    assert _latest_data_month(db, p.id, TODAY) == (2026, 6)


# --- window threading --------------------------------------------------------


def test_executive_report_honors_explicit_month_window(db):
    p = _prop(db)
    gu = _upload(db, p.id, SourceType.GSC)
    _gsc(db, p.id, gu, date(2026, 6, 10), 30, 400)
    r = build_executive_report(
        db, p.id, days=30, want_compare=True,
        window=(date(2026, 6, 1), date(2026, 6, 30)),
        prev_window=(date(2026, 5, 1), date(2026, 5, 31)),
    )
    assert r["window"]["start"] == "2026-06-01"
    assert r["window"]["end"] == "2026-06-30"
    assert r["window"]["anchored_to_latest_data"] is False
    assert r["previous_window"]["start"] == "2026-05-01"


# --- health composition ------------------------------------------------------


@pytest.fixture()
def briefed(db):
    p = _prop(db)
    gu = _upload(db, p.id, SourceType.GSC)
    au = _upload(db, p.id, SourceType.GA4)
    _gsc(db, p.id, gu, date(2026, 6, 12), 40, 500)
    _ga4(db, p.id, au, date(2026, 6, 12), 100, 80)  # 80% engaged -> good/excellent
    _content(db, p.id)
    return p


def test_health_is_a_count_not_an_opaque_score(db, briefed):
    b = compose_briefing(db, briefed.id, 2026, 6, today=TODAY)
    health = b["health"]
    # No composite index anywhere; health is a count of healthy modules.
    assert "healthy_count" in health and "assessable_count" in health
    assert "score" not in health
    assert health["healthy_count"] <= health["assessable_count"]
    assert str(health["healthy_count"]) in health["summary"]


def test_every_module_status_is_explainable(db, briefed):
    b = compose_briefing(db, briefed.id, 2026, 6, today=TODAY)
    keys = {m["key"] for m in b["health"]["modules"]}
    assert keys == {"seo", "ai_visibility", "content", "reviews", "website"}
    for m in b["health"]["modules"]:
        assert m["status"] in STATUS_LABELS
        assert m["reason"]  # a one-sentence explanation, always
        assert m["details_href"]
        assert "—" not in m["reason"]  # no em dashes in copy


def test_missing_and_unconnected_modules_are_honest_not_zero(db):
    # A bare property: no SEO/GA4/reviews. Those modules must say so, not band 0.
    p = _prop(db, "Bare Court")
    b = compose_briefing(db, p.id, 2026, 6, today=TODAY)
    by = {m["key"]: m for m in b["health"]["modules"]}
    assert by["reviews"]["status"] == NOT_CONNECTED
    assert by["website"]["status"] == NOT_CONNECTED
    assert by["seo"]["status"] == NOT_ENOUGH_DATA
    # Assessable count excludes not-connected/not-enough-data modules.
    assert b["health"]["assessable_count"] <= 5


def test_website_health_reflects_engagement(db, briefed):
    b = compose_briefing(db, briefed.id, 2026, 6, today=TODAY)
    website = next(m for m in b["health"]["modules"] if m["key"] == "website")
    assert website["status"] in ("excellent", "good")  # 80% engaged
    assert "80%" in website["reason"] or "engaged" in website["reason"]


def test_content_health_from_score(db, briefed):
    b = compose_briefing(db, briefed.id, 2026, 6, today=TODAY)
    content = next(m for m in b["health"]["modules"] if m["key"] == "content")
    assert content["status"] in ("excellent", "good", "fair", "needs_attention")
    assert "score" in content["reason"].lower()


# --- adaptive + composition --------------------------------------------------


def test_adaptive_sections_are_connect_me_cards(db, briefed):
    b = compose_briefing(db, briefed.id, 2026, 6, today=TODAY)
    keys = {s["key"] for s in b["adaptive_sections"]}
    assert "leasing" in keys and "competitors" in keys
    for s in b["adaptive_sections"]:
        assert s["connected"] is False
        assert s["cta"] and s["message"]


def test_briefing_has_summary_kpis_priorities(db, briefed):
    b = compose_briefing(db, briefed.id, 2026, 6, today=TODAY)
    assert b["period"]["label"] == "June 2026"
    assert b["comparison_period"]["label"] == "May 2026"
    assert isinstance(b["executive_summary"], list)
    assert isinstance(b["kpis"], list) and len(b["kpis"]) >= 1
    assert len(b["top_priorities"]) <= 5


# --- endpoints + snapshots ---------------------------------------------------


def test_briefing_endpoint_scope_and_404(client):
    assert client.get("/api/briefing").json()["scope_required"] is True
    assert client.get("/api/briefing?property_id=999").status_code == 404


def test_snapshot_freeze_and_history(client, db, briefed):
    gen = client.post(f"/api/briefing/generate?property_id={briefed.id}&year=2026&month=6")
    assert gen.status_code == 200
    sid = gen.json()["id"]

    hist = client.get(f"/api/briefing/history?property_id={briefed.id}").json()
    assert len(hist["snapshots"]) == 1
    assert hist["snapshots"][0]["period_label"] == "June 2026"

    snap = client.get(f"/api/briefing/{sid}").json()
    assert snap["frozen"] is True
    assert snap["period"]["label"] == "June 2026"

    # Regenerating the same month upserts (one snapshot per property+month).
    client.post(f"/api/briefing/generate?property_id={briefed.id}&year=2026&month=6")
    hist2 = client.get(f"/api/briefing/history?property_id={briefed.id}").json()
    assert len(hist2["snapshots"]) == 1


def test_snapshot_is_frozen_against_later_data(client, db, briefed):
    gen = client.post(f"/api/briefing/generate?property_id={briefed.id}&year=2026&month=6")
    sid = gen.json()["id"]
    frozen = client.get(f"/api/briefing/{sid}").json()
    frozen_website = next(m for m in frozen["health"]["modules"] if m["key"] == "website")

    # Add more June GA4 data AFTER freezing; the snapshot must not change.
    au = _upload(db, briefed.id, SourceType.GA4)
    _ga4(db, briefed.id, au, date(2026, 6, 20), 500, 50)  # would drop engagement
    still = client.get(f"/api/briefing/{sid}").json()
    still_website = next(m for m in still["health"]["modules"] if m["key"] == "website")
    assert still_website == frozen_website  # frozen snapshot unchanged


def test_briefing_scope_isolation(client, db, briefed):
    other = _prop(db, "Separate Court")
    b = client.get(f"/api/briefing?property_id={other.id}&year=2026&month=6").json()
    by = {m["key"]: m for m in b["health"]["modules"]}
    # The other property has no data of its own.
    assert by["seo"]["status"] == NOT_ENOUGH_DATA
    assert by["website"]["status"] == NOT_CONNECTED
