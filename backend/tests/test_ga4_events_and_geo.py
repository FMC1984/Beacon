"""GA4 events (sync + CSV + reporting) and city/region in the GA4 sync.

The gaps these close: the live GA4 sync now pulls city/region (so the Audience
report populates from the connection, not just uploads) and event-name counts
(a data type Beacon previously collapsed away), surfaced on the Dashboard and
SEO report. All Google HTTP is monkeypatched; no network.
"""

import io

import pytest

from app.config import settings
from app.models import (
    DataConnection,
    GA4EventsDaily,
    GA4SessionsDaily,
    OAuthStatus,
    Property,
    SourceType,
    SyncJobStatus,
)
from app.services.google_sync import gapi
from app.services.google_sync import sync as sync_mod
from app.services.ingestion.common import UploadValidationError
from app.services.ingestion.ga4_events import parse_ga4_events_csv
from app.services.metrics import build_dashboard
from app.services.reporting_events import build_events_section
from app.services.reporting_seo import build_seo_report


def _prop(db, name="Events Manor"):
    p = Property(name=name, slug=name.lower().replace(" ", "-"))
    db.add(p)
    db.commit()
    return p


def _ga4_conn(db, prop):
    conn = DataConnection(
        property_id=prop.id,
        source_type=SourceType.GA4,
        account_name="tina@example.com",
        external_account_id="tina@example.com",
        oauth_status=OAuthStatus.CONNECTED,
        refresh_token="rt",
        resource_id="properties/123",
        resource_name="Example",
    )
    db.add(conn)
    db.commit()
    return conn


# --- city/region in the GA4 sync ---------------------------------------------


def test_ga4_run_report_parses_city_region(monkeypatch):
    fake = {
        "rows": [
            {
                "dimensionValues": [
                    {"value": "20260701"}, {"value": "google"}, {"value": "organic"},
                    {"value": "/"}, {"value": "Denver"}, {"value": "Colorado"},
                ],
                "metricValues": [
                    {"value": "40"}, {"value": "30"}, {"value": "38"}, {"value": "2"}
                ],
            },
            {
                "dimensionValues": [
                    {"value": "20260701"}, {"value": "google"}, {"value": "organic"},
                    {"value": "/"}, {"value": "(not set)"}, {"value": "(not set)"},
                ],
                "metricValues": [
                    {"value": "5"}, {"value": "2"}, {"value": "5"}, {"value": "0"}
                ],
            },
        ]
    }
    monkeypatch.setattr(gapi, "_request", lambda *a, **k: fake)
    from datetime import date

    rows = gapi.ga4_run_report("tok", "properties/123", date(2026, 7, 1), date(2026, 7, 1))
    assert rows[0]["city"] == "Denver" and rows[0]["region"] == "Colorado"
    assert rows[1]["city"] is None and rows[1]["region"] is None  # (not set) -> NULL


def test_ga4_sync_writes_city_region_and_events(client, db, monkeypatch):
    prop = _prop(db)
    conn = _ga4_conn(db, prop)
    monkeypatch.setattr(sync_mod, "refresh_access_token", lambda rt: "at")
    monkeypatch.setattr(
        gapi, "ga4_run_report",
        lambda t, res, lo, hi: [
            {"date": hi, "session_source": "google", "session_medium": "organic",
             "landing_page": "/", "city": "Denver", "region": "Colorado",
             "sessions": 40, "engaged_sessions": 30, "total_users": 38, "key_events": 2},
        ],
    )
    monkeypatch.setattr(
        gapi, "ga4_events_report",
        lambda t, res, lo, hi: [
            {"date": hi, "event_name": "page_view", "event_count": 100, "total_users": 40},
            {"date": hi, "event_name": "scroll", "event_count": 30, "total_users": 20},
        ],
    )
    job = sync_mod.run_google_sync(db, conn.id)
    assert job.status == SyncJobStatus.COMPLETED

    session_rows = db.query(GA4SessionsDaily).filter_by(property_id=prop.id).all()
    assert session_rows[0].city == "Denver" and session_rows[0].region == "Colorado"

    events = db.query(GA4EventsDaily).filter_by(property_id=prop.id).all()
    assert {e.event_name for e in events} == {"page_view", "scroll"}
    assert all(e.sync_job_id is not None and e.upload_id is None for e in events)


# --- events CSV import --------------------------------------------------------


def test_events_count_reported_in_sync_response(client, db, monkeypatch):
    prop = _prop(db)
    conn = _ga4_conn(db, prop)
    monkeypatch.setattr(sync_mod, "refresh_access_token", lambda rt: "at")
    monkeypatch.setattr(gapi, "ga4_run_report", lambda t, res, lo, hi: [])
    monkeypatch.setattr(
        gapi, "ga4_events_report",
        lambda t, res, lo, hi: [
            {"date": hi, "event_name": "page_view", "event_count": 100, "total_users": 40},
        ],
    )
    body = client.post(f"/api/google/connections/{conn.id}/sync").json()
    assert body["status"] == "completed"
    assert body["events_imported"] == 1
    assert body["events_error"] is None


def test_events_pull_failure_is_non_fatal(client, db, monkeypatch):
    """A failing events pull must not fail the whole sync: sessions/cities still
    commit, and the error is surfaced rather than swallowed."""
    prop = _prop(db)
    conn = _ga4_conn(db, prop)
    monkeypatch.setattr(sync_mod, "refresh_access_token", lambda rt: "at")
    monkeypatch.setattr(
        gapi, "ga4_run_report",
        lambda t, res, lo, hi: [
            {"date": hi, "session_source": "google", "session_medium": "organic",
             "landing_page": "/", "city": "Denver", "region": "Colorado",
             "sessions": 5, "engaged_sessions": 3, "total_users": 5, "key_events": 0},
        ],
    )

    def boom(*a, **k):
        raise RuntimeError("GA4 events dimension rejected")

    monkeypatch.setattr(gapi, "ga4_events_report", boom)
    body = client.post(f"/api/google/connections/{conn.id}/sync").json()
    assert body["status"] == "completed"  # sync still succeeds
    assert body["rows_imported"] == 1  # sessions committed
    assert body["events_imported"] == 0
    assert "rejected" in body["events_error"]
    # City still landed despite the events failure.
    assert db.query(GA4SessionsDaily).filter_by(property_id=prop.id).one().city == "Denver"


def test_events_csv_with_date_column():
    csv = (
        "Date,Event name,Event count,Total users\n"
        "20260701,page_view,120,50\n"
        "20260701,scroll,40,25\n"
        "20260701,Total,160,50\n"  # totals row skipped
    ).encode()
    parsed = parse_ga4_events_csv(csv)
    names = {r["event_name"] for r in parsed.rows}
    assert names == {"page_view", "scroll"}


def test_events_csv_without_date_uses_preamble_range():
    csv = (
        "# Start date: 20260601\n"
        "# End date: 20260630\n"
        "Event name,Event count,Total users\n"
        "page_view,6231,1538\n"
        "user_engagement,4847,922\n"
    ).encode()
    parsed = parse_ga4_events_csv(csv)
    assert len(parsed.rows) == 2
    assert all(r["date"].isoformat() == "2026-06-30" for r in parsed.rows)
    assert parsed.warnings  # discloses the single-day stamping


def test_events_csv_without_any_date_is_rejected():
    csv = b"Event name,Event count,Total users\npage_view,10,5\n"
    with pytest.raises(UploadValidationError):
        parse_ga4_events_csv(csv)


def test_events_upload_endpoint(client, db):
    prop = _prop(db)
    csv = b"Date,Event name,Event count,Total users\n20260701,page_view,120,50\n20260701,click,12,8\n"
    r = client.post(
        f"/api/uploads/ga4_events",
        data={"property_id": prop.id},
        files={"file": ("events.csv", io.BytesIO(csv), "text/csv")},
    )
    assert r.status_code == 201, r.text
    assert r.json()["rows_ingested"] == 2
    assert db.query(GA4EventsDaily).filter_by(property_id=prop.id).count() == 2


# --- events reporting on dashboard + SEO --------------------------------------


def _seed_events(db, prop):
    from datetime import date
    from app.models import Upload, UploadStatus

    up = Upload(source_type=SourceType.GA4, property_id=prop.id, filename="e.csv",
                status=UploadStatus.PROCESSED)
    db.add(up)
    db.flush()
    for name, count, users in [("page_view", 6231, 1538), ("user_engagement", 4847, 922), ("scroll", 952, 512)]:
        db.add(GA4EventsDaily(property_id=prop.id, upload_id=up.id, date=date(2026, 7, 1),
                              event_name=name, event_count=count, total_users=users))
    db.commit()


def test_events_section_aggregates_and_ranks(db):
    prop = _prop(db)
    _seed_events(db, prop)
    from datetime import date

    section = build_events_section(db, [prop.id], date(2026, 6, 1), date(2026, 7, 31), date(2026, 7, 13))
    assert section["distinct_events"] == 3
    assert section["events"][0]["event_name"] == "page_view"  # highest count first
    assert section["total_event_count"] == 6231 + 4847 + 952
    assert section["events"][0]["per_user"] is not None


def test_events_appear_on_dashboard_and_seo(db):
    prop = _prop(db)
    _seed_events(db, prop)
    dash = build_dashboard(db, prop.id, days=365)
    assert dash["events"] is not None
    assert dash["events"]["distinct_events"] == 3
    seo = build_seo_report(db, prop.id, days=365)
    assert seo["events"] is not None
    assert seo["events"]["events"][0]["event_name"] == "page_view"
