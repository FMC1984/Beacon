"""GSC query-snapshot ingestion: uploads without a Date column but with a
preamble-derived period range, via the real /api/uploads/gsc endpoint."""

from datetime import date

from app.models import GSCPerformanceDaily
from tests.test_phase2_uploads import make_property, post_upload


def test_snapshot_upload_end_to_end(client, db):
    prop = make_property(client, "DCHP")
    resp = post_upload(client, "gsc", prop["id"], "gsc_queries_dchp_no_date.csv")
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["rows_ingested"] == 678
    assert body["date_start"] == "2026-06-01"
    assert body["date_end"] == "2026-06-30"
    assert body["warnings"] is not None
    assert "period total" in body["warnings"][0]

    rows = db.query(GSCPerformanceDaily).filter_by(property_id=prop["id"]).all()
    assert len(rows) == 678
    assert all(r.date == date(2026, 6, 30) for r in rows)
    assert all(r.query is not None for r in rows)


def test_snapshot_reupload_replaces_only_snapshot_rows(client, db):
    prop = make_property(client, "DCHP Reupload")
    first = post_upload(client, "gsc", prop["id"], "gsc_queries_dchp_no_date.csv")
    second = post_upload(client, "gsc", prop["id"], "gsc_queries_dchp_no_date.csv")
    assert second.json()["rows_replaced"] == 678
    assert first.json()["rows_replaced"] == 0
    assert (
        db.query(GSCPerformanceDaily).filter_by(property_id=prop["id"]).count() == 678
    )


def test_snapshot_does_not_clobber_true_daily_row_same_date(client, db):
    """A real Dates-tab upload covering 2026-06-30 stores a query=None row on
    that date. Later uploading a query snapshot ending on the same date must
    not delete that daily row."""
    prop = make_property(client, "DCHP Mixed")
    post_upload(client, "gsc", prop["id"], "gsc_dates.csv")  # covers 2026-06-01..03
    daily_count_before = (
        db.query(GSCPerformanceDaily)
        .filter_by(property_id=prop["id"])
        .filter(GSCPerformanceDaily.query.is_(None))
        .count()
    )
    assert daily_count_before == 3

    post_upload(client, "gsc", prop["id"], "gsc_queries_dchp_no_date.csv")  # ends 06-30

    daily_count_after = (
        db.query(GSCPerformanceDaily)
        .filter_by(property_id=prop["id"])
        .filter(GSCPerformanceDaily.query.is_(None))
        .count()
    )
    assert daily_count_after == 3  # untouched
    snapshot_count = (
        db.query(GSCPerformanceDaily)
        .filter_by(property_id=prop["id"])
        .filter(GSCPerformanceDaily.query.isnot(None))
        .count()
    )
    assert snapshot_count == 678
