from app.models import GA4SessionsDaily, GSCPerformanceDaily, Upload, UploadStatus
from tests.conftest import fixture_bytes


def make_property(client, name="Solara Flats"):
    resp = client.post("/api/properties", json={"name": name, "city": "Tempe", "state": "AZ"})
    assert resp.status_code == 201, resp.text
    return resp.json()


def post_upload(client, source, property_id, fixture_name):
    return client.post(
        f"/api/uploads/{source}",
        data={"property_id": property_id},
        files={"file": (fixture_name, fixture_bytes(fixture_name), "text/csv")},
    )


def test_ga4_upload_end_to_end(client, db):
    prop = make_property(client)
    resp = post_upload(client, "ga4", prop["id"], "ga4_traffic_with_date.csv")
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["status"] == "processed"
    assert body["rows_ingested"] == 5
    assert body["rows_skipped"] == 1
    assert body["date_start"] == "2026-06-01"
    assert body["date_end"] == "2026-06-03"

    rows = db.query(GA4SessionsDaily).filter_by(property_id=prop["id"]).all()
    assert len(rows) == 5
    assert all(r.upload_id == body["upload_id"] for r in rows)
    # Since Phase 3, rows are classified at ingest (2 AI referral rows in fixture).
    assert sum(r.is_ai_referral for r in rows) == 2


def test_ga4_reupload_is_idempotent(client, db):
    prop = make_property(client)
    first = post_upload(client, "ga4", prop["id"], "ga4_traffic_with_date.csv")
    second = post_upload(client, "ga4", prop["id"], "ga4_traffic_with_date.csv")
    assert second.status_code == 201
    assert second.json()["rows_replaced"] == 5
    count = db.query(GA4SessionsDaily).filter_by(property_id=prop["id"]).count()
    assert count == 5
    assert first.json()["rows_replaced"] == 0


def test_ga4_bad_file_recorded_as_failed(client, db):
    prop = make_property(client)
    resp = post_upload(client, "ga4", prop["id"], "ga4_missing_date.csv")
    assert resp.status_code == 422
    assert "Date" in resp.json()["detail"]

    uploads = db.query(Upload).all()
    assert len(uploads) == 1
    assert uploads[0].status == UploadStatus.FAILED
    assert "Date" in uploads[0].error_message
    assert db.query(GA4SessionsDaily).count() == 0


def test_gsc_upload_end_to_end(client, db):
    prop = make_property(client)
    resp = post_upload(client, "gsc", prop["id"], "gsc_dates.csv")
    assert resp.status_code == 201, resp.text
    assert resp.json()["rows_ingested"] == 3
    rows = db.query(GSCPerformanceDaily).filter_by(property_id=prop["id"]).all()
    assert {r.clicks for r in rows} == {12, 15, 9}


def test_gsc_no_date_export_rejected(client, db):
    prop = make_property(client)
    resp = post_upload(client, "gsc", prop["id"], "gsc_queries_no_date.csv")
    assert resp.status_code == 422
    assert "Dates tab" in resp.json()["detail"]


def test_upload_to_unknown_property_404(client):
    resp = post_upload(client, "ga4", 999, "ga4_traffic_with_date.csv")
    assert resp.status_code == 404


def test_upload_history_lists_both_outcomes(client):
    prop = make_property(client)
    post_upload(client, "ga4", prop["id"], "ga4_traffic_with_date.csv")
    post_upload(client, "gsc", prop["id"], "gsc_queries_no_date.csv")
    history = client.get("/api/uploads").json()
    assert len(history) == 2
    statuses = {(u["source_type"], u["status"]) for u in history}
    assert statuses == {("ga4", "processed"), ("gsc", "failed")}


def test_duplicate_property_rejected(client):
    make_property(client)
    resp = client.post("/api/properties", json={"name": "Solara Flats"})
    assert resp.status_code == 409
