import pytest

from app.models import GBPMetricsDaily, PaidMediaDaily
from app.services.ingestion.common import UploadValidationError
from app.services.ingestion.gbp import parse_gbp_csv
from app.services.ingestion.paid import parse_paid_csv
from tests.conftest import fixture_bytes
from tests.test_phase2_uploads import make_property, post_upload


# --- parsers ---


def test_gbp_sums_desktop_mobile_and_flags_unmapped():
    result = parse_gbp_csv(fixture_bytes("gbp_performance.csv"))
    assert len(result.rows) == 3
    first = result.rows[0]
    assert first["search_impressions"] == 165  # 45 desktop + 120 mobile
    assert first["maps_impressions"] == 50  # 12 + 38
    assert first["calls"] == 3
    assert first["direction_requests"] == 7
    assert first["website_clicks"] == 14
    # Unknown columns are surfaced, never silently dropped.
    assert result.unmapped_columns == ["Bookings"]


def test_gbp_duplicate_dates_rejected():
    with pytest.raises(UploadValidationError, match="Multiple rows for 2026-06-01"):
        parse_gbp_csv(fixture_bytes("gbp_duplicate_dates.csv"))


def test_paid_google_ads_preamble_totals_and_money():
    result = parse_paid_csv(fixture_bytes("google_ads_campaigns.csv"))
    assert len(result.rows) == 3
    first = result.rows[0]
    assert first["campaign_name"] == "Brand - Solara Flats"
    assert first["spend"] == pytest.approx(145.32)
    assert first["conversions"] == pytest.approx(4.5)
    assert [s["reason"] for s in result.skipped] == ["totals row"]


def test_paid_meta_headers():
    result = parse_paid_csv(fixture_bytes("meta_campaigns.csv"))
    assert len(result.rows) == 2
    assert result.rows[0]["clicks"] == 140  # Link clicks alias
    assert result.rows[0]["spend"] == pytest.approx(62.45)
    assert result.rows[0]["conversions"] == 6  # Results alias


# --- endpoints ---


def post_paid(client, property_id, fixture_name, platform):
    return client.post(
        "/api/uploads/paid_media",
        data={"property_id": property_id, "platform": platform},
        files={"file": (fixture_name, fixture_bytes(fixture_name), "text/csv")},
    )


def test_gbp_upload_end_to_end(client, db):
    prop = make_property(client)
    resp = post_upload(client, "gbp", prop["id"], "gbp_performance.csv")
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["rows_ingested"] == 3
    assert body["unmapped_columns"] == ["Bookings"]
    rows = db.query(GBPMetricsDaily).filter_by(property_id=prop["id"]).all()
    assert len(rows) == 3
    assert {r.search_impressions for r in rows} == {165, 183, 136}


def test_gbp_reupload_idempotent(client, db):
    prop = make_property(client)
    post_upload(client, "gbp", prop["id"], "gbp_performance.csv")
    second = post_upload(client, "gbp", prop["id"], "gbp_performance.csv")
    assert second.json()["rows_replaced"] == 3
    assert db.query(GBPMetricsDaily).count() == 3


def test_paid_upload_end_to_end(client, db):
    prop = make_property(client)
    resp = post_paid(client, prop["id"], "google_ads_campaigns.csv", "google_ads")
    assert resp.status_code == 201, resp.text
    rows = db.query(PaidMediaDaily).filter_by(property_id=prop["id"]).all()
    assert len(rows) == 3
    assert all(r.platform == "google_ads" for r in rows)
    assert float(sum(r.spend for r in rows)) == pytest.approx(595.17)


def test_paid_replacement_scoped_by_platform(client, db):
    prop = make_property(client)
    post_paid(client, prop["id"], "google_ads_campaigns.csv", "google_ads")
    # Meta upload covers overlapping dates but must not wipe Google Ads rows.
    resp = post_paid(client, prop["id"], "meta_campaigns.csv", "meta")
    assert resp.json()["rows_replaced"] == 0
    platforms = {r.platform for r in db.query(PaidMediaDaily).all()}
    assert platforms == {"google_ads", "meta"}
    assert db.query(PaidMediaDaily).count() == 5

    # Re-uploading the Google Ads file replaces only Google Ads rows.
    again = post_paid(client, prop["id"], "google_ads_campaigns.csv", "google_ads")
    assert again.json()["rows_replaced"] == 3
    assert db.query(PaidMediaDaily).count() == 5


def test_paid_unknown_platform_rejected(client):
    prop = make_property(client)
    resp = post_paid(client, prop["id"], "google_ads_campaigns.csv", "tiktok")
    assert resp.status_code == 422
    assert "platform must be one of" in resp.json()["detail"]


def test_phase4_uploads_have_no_ai_fields(client):
    # AI classification applies to GA4 traffic only; hard rule 3 disclosure
    # travels with AI numbers, and these responses carry neither.
    prop = make_property(client)
    gbp = post_upload(client, "gbp", prop["id"], "gbp_performance.csv").json()
    paid = post_paid(client, prop["id"], "meta_campaigns.csv", "meta").json()
    for body in (gbp, paid):
        assert body["ai_rows_detected"] is None
        assert body["disclosure"] is None
