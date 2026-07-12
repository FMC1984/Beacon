"""Phase 6 acceptance scenarios from Tina's checklist, made deterministic by
passing a fixed `today` to the metrics service (never date-dependent tests)."""

from datetime import date

from app.constants import AI_TRAFFIC_DISCLOSURE
from app.services.metrics import build_dashboard
from tests.test_phase2_uploads import make_property, post_upload

TODAY = date(2026, 7, 4)


def test_ai_absent_still_carries_disclosure_and_empty_mix(client, db):
    prop = make_property(client, "No AI Property")
    post_upload(client, "ga4", prop["id"], "ga4_no_ai_recent.csv")

    body = build_dashboard(db, prop["id"], 30, today=TODAY)
    ga4 = body["ga4"]
    assert ga4["ai_sessions"] == 0
    assert ga4["ai_share"] == 0.0
    assert ga4["platform_mix"] == []
    # Zero is still an AI traffic number; the disclosure never disappears.
    assert ga4["disclosure"] == AI_TRAFFIC_DISCLOSURE


def test_fresh_data_has_no_freshness_warning(client, db):
    prop = make_property(client, "Fresh Property")
    post_upload(client, "ga4", prop["id"], "ga4_no_ai_recent.csv")  # Jul 1-3
    body = build_dashboard(db, prop["id"], 30, today=TODAY)
    assert body["ga4"]["provenance"]["freshness_warning"] is None


def test_stale_data_has_freshness_warning(client, db):
    prop = make_property(client, "Stale Property")
    post_upload(client, "ga4", prop["id"], "ga4_traffic_with_date.csv")  # Jun 1-3
    body = build_dashboard(db, prop["id"], 30, today=TODAY)
    warning = body["ga4"]["provenance"]["freshness_warning"]
    assert warning is not None and "2026-06-03" in warning


def test_multiple_ai_sources_in_platform_mix(client, db):
    prop = make_property(client, "Multi AI Property")
    post_upload(client, "ga4", prop["id"], "ga4_traffic_with_date.csv")
    post_upload(client, "ga4", prop["id"], "ga4_multi_ai.csv")
    body = build_dashboard(db, prop["id"], 30, today=TODAY)
    platforms = {m["platform"] for m in body["ga4"]["platform_mix"]}
    assert platforms == {"chatgpt", "perplexity", "claude", "gemini", "grok"}


def test_missing_crm_section_is_null_not_zeroes(client, db):
    prop = make_property(client, "No CRM Property")
    post_upload(client, "ga4", prop["id"], "ga4_traffic_with_date.csv")
    body = build_dashboard(db, prop["id"], 30, today=TODAY)
    assert body["crm"] is None  # hidden, never rendered as fake zeroes


def test_property_with_no_data_is_all_null(client, db):
    prop = make_property(client, "Empty Property")
    body = build_dashboard(db, prop["id"], 30, today=TODAY)
    assert all(
        body[k] is None for k in ("ga4", "gsc", "gbp", "paid", "crm")
    )


def test_every_returned_section_has_complete_envelope(client, db):
    prop = make_property(client, "Envelope Property")
    post_upload(client, "ga4", prop["id"], "ga4_traffic_with_date.csv")
    post_upload(client, "gsc", prop["id"], "gsc_dates.csv")
    body = build_dashboard(db, prop["id"], 30, today=TODAY)
    for key in ("ga4", "gsc"):
        prov = body[key]["provenance"]
        assert set(prov) == {
            "source",
            "date_start",
            "date_end",
            "last_updated",
            "freshness_warning",
        }
        assert prov["source"] and prov["date_start"] and prov["last_updated"]
