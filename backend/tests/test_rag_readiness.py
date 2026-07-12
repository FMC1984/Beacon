"""RAG readiness: ingestion preserves citation-grade provenance (raw file, source
account, date range, per-row source line) without any RAG code existing yet."""

from datetime import date
from pathlib import Path

from sqlalchemy import inspect

from app.models import GA4SessionsDaily, Upload
from tests.conftest import fixture_bytes
from tests.test_phase1_schema import migrate_fresh_db
from tests.test_phase2_uploads import make_property


def upload_ga4(client, property_id, source_account=None):
    data = {"property_id": property_id}
    if source_account:
        data["source_account"] = source_account
    return client.post(
        "/api/uploads/ga4",
        data=data,
        files={
            "file": (
                "ga4_traffic_with_date.csv",
                fixture_bytes("ga4_traffic_with_date.csv"),
                "text/csv",
            )
        },
    )


def test_upload_persists_provenance(client, db):
    prop = make_property(client)
    resp = upload_ga4(client, prop["id"], source_account="GA4 property 498231775")
    assert resp.status_code == 201, resp.text

    upload = db.query(Upload).one()
    assert upload.source_account == "GA4 property 498231775"
    assert upload.date_start == date(2026, 6, 1)
    assert upload.date_end == date(2026, 6, 3)

    # Raw source payload is retained byte-for-byte.
    stored = Path(upload.stored_path)
    assert stored.exists()
    assert stored.read_bytes() == fixture_bytes("ga4_traffic_with_date.csv")
    assert stored.name == f"{upload.id}_ga4_traffic_with_date.csv"


def test_rows_carry_source_line(client, db):
    prop = make_property(client)
    upload_ga4(client, prop["id"])
    lines = {
        r.source_line for r in db.query(GA4SessionsDaily).all()
    }
    # Header is file line 7 (after the GA4 preamble); the 5 data rows are 8-12.
    assert lines == {8, 9, 10, 11, 12}


def test_raw_file_kept_even_when_ingest_fails(client, db):
    prop = make_property(client)
    resp = client.post(
        "/api/uploads/ga4",
        data={"property_id": prop["id"]},
        files={
            "file": (
                "ga4_missing_date.csv",
                fixture_bytes("ga4_missing_date.csv"),
                "text/csv",
            )
        },
    )
    assert resp.status_code == 422
    upload = db.query(Upload).one()
    assert upload.stored_path and Path(upload.stored_path).exists()


def test_sync_jobs_and_uploads_have_citation_columns(tmp_path):
    insp = inspect(migrate_fresh_db(tmp_path))
    upload_cols = {c["name"] for c in insp.get_columns("uploads")}
    assert {"source_account", "date_start", "date_end", "stored_path"} <= upload_cols
    job_cols = {c["name"] for c in insp.get_columns("sync_jobs")}
    assert {"report_type", "endpoint", "date_start", "date_end"} <= job_cols
    for table in (
        "ga4_sessions_daily",
        "gsc_performance_daily",
        "gbp_metrics_daily",
        "paid_media_daily",
    ):
        cols = {c["name"] for c in insp.get_columns(table)}
        assert "source_line" in cols
