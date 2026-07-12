"""Google connections schema: tables exist as specified, and the dual-provenance
rule (every data row references an upload or a sync job) is enforced by the DB."""

from datetime import date

import pytest
from sqlalchemy import inspect
from sqlalchemy.exc import IntegrityError

from app.models import GA4SessionsDaily, Property, SourceType, Upload

from tests.test_phase1_schema import migrate_fresh_db


def test_connection_tables_have_specified_columns(tmp_path):
    insp = inspect(migrate_fresh_db(tmp_path))
    conn_cols = {c["name"] for c in insp.get_columns("data_connections")}
    assert {
        "source_type",
        "account_name",
        "external_account_id",
        "oauth_status",
        "last_sync_at",
        "sync_frequency",
        "sync_status",
        "error_message",
    } <= conn_cols
    job_cols = {c["name"] for c in insp.get_columns("sync_jobs")}
    assert {
        "connection_id",
        "source_type",
        "started_at",
        "completed_at",
        "status",
        "rows_imported",
        "rows_updated",
        "error_message",
    } <= job_cols


def test_data_tables_support_sync_provenance(tmp_path):
    insp = inspect(migrate_fresh_db(tmp_path))
    for table in (
        "ga4_sessions_daily",
        "gsc_performance_daily",
        "gbp_metrics_daily",
        "paid_media_daily",
        "crm_leads",
    ):
        cols = {c["name"]: c for c in insp.get_columns(table)}
        assert "sync_job_id" in cols
        assert cols["upload_id"]["nullable"] is True


def ga4_row(**overrides):
    defaults = dict(
        property_id=1,
        date=date(2026, 6, 1),
        session_source="google",
        session_medium="organic",
        sessions=10,
    )
    defaults.update(overrides)
    return GA4SessionsDaily(**defaults)


def test_row_without_any_provenance_rejected(db):
    db.add(Property(id=1, name="P", slug="p"))
    db.commit()
    db.add(ga4_row())
    with pytest.raises(IntegrityError):
        db.commit()
    db.rollback()

    upload = Upload(source_type=SourceType.GA4, filename="x.csv", property_id=1)
    db.add(upload)
    db.flush()
    db.add(ga4_row(upload_id=upload.id))
    db.commit()
    assert db.query(GA4SessionsDaily).count() == 1
