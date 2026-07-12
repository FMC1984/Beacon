"""Tolerant GA4 ingestion: event-level exports collapse to true sessions,
"Date + hour" parses, duplicate/segment columns are handled, and honest errors
remain for files whose numbers cannot be trusted."""

import pytest

from app.models import GA4SessionsDaily
from app.services.ingestion.common import UploadValidationError, parse_export_date
from app.services.ingestion.ga4 import parse_ga4_csv
from tests.conftest import fixture_bytes
from tests.test_phase2_uploads import make_property, post_upload

EVENT_FIXTURE = "ga4_event_level_exploration.csv"


def test_date_plus_hour_truncates_to_date():
    assert parse_export_date("2026060708").isoformat() == "2026-06-07"
    assert parse_export_date("20260607").isoformat() == "2026-06-07"  # still works
    assert parse_export_date("2026-06-07").isoformat() == "2026-06-07"


def test_event_level_collapses_to_true_sessions():
    parsed = parse_ga4_csv(fixture_bytes(EVENT_FIXTURE))
    # Two real sessions groups: google/"/" and chatgpt/"/floorplans".
    assert len(parsed.rows) == 2
    total = sum(r["sessions"] for r in parsed.rows)
    # Matches the file's own Grand Total (10), NOT the 30 you'd get by summing
    # every event row.
    assert total == 10
    assert parsed.warnings and "session_start" in parsed.warnings[0]


def test_event_level_key_events_summed_across_events():
    parsed = parse_ga4_csv(fixture_bytes(EVENT_FIXTURE))
    assert sum(r["key_events"] for r in parsed.rows) == 1


def test_event_level_preserves_landing_and_source():
    parsed = parse_ga4_csv(fixture_bytes(EVENT_FIXTURE))
    by_source = {r["session_source"]: r for r in parsed.rows}
    assert by_source["chatgpt.com"]["landing_page"] == "/floorplans"
    assert by_source["chatgpt.com"]["sessions"] == 6
    assert by_source["google"]["session_medium"] == "organic"


def test_event_level_ai_detected_after_collapse(client, db):
    prop = make_property(client, "Event Level Prop")
    resp = post_upload(client, "ga4", prop["id"], EVENT_FIXTURE)
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["rows_ingested"] == 2
    assert body["ai_rows_detected"] == 1
    assert body["warnings"]  # the collapse is disclosed to the user

    rows = db.query(GA4SessionsDaily).filter_by(property_id=prop["id"]).all()
    ai = [r for r in rows if r.is_ai_referral]
    assert len(ai) == 1
    assert ai[0].ai_platform == "chatgpt"
    assert ai[0].sessions == 6
    assert sum(r.sessions for r in rows) == 10


def test_event_level_without_session_start_is_rejected_clearly():
    csv = (
        "Session source / medium,Date + hour (YYYYMMDDHH),Landing page,Event name,Sessions,Key events\n"
        "google / organic,2026060708,/,page_view,4,0\n"
        "google / organic,2026060708,/,scroll,4,0\n"
    ).encode()
    with pytest.raises(UploadValidationError, match="session_start"):
        parse_ga4_csv(csv)


def test_standard_traffic_report_still_works():
    parsed = parse_ga4_csv(fixture_bytes("ga4_traffic_with_date.csv"))
    assert parsed.rows
    assert not parsed.warnings  # no event dimension, no collapse
    assert all("event_name" not in r for r in parsed.rows)


def test_nth_day_export_rejected_with_guidance():
    csv = b"Nth day,Session source / medium,Sessions\n0000,google / organic,10\n"
    with pytest.raises(UploadValidationError, match="Nth day"):
        parse_ga4_csv(csv)
