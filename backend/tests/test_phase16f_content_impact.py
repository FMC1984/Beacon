"""Phase 16F: Content change log, Content Impact report, and RAG index health.

The load-bearing rules: recording a change never asserts causation (the
external-factors caveat rides on every comparison and no causal verbs appear);
before/after math is a plain observed delta; an after-window that has not fully
elapsed is disclosed, not shown as a decline to zero; and the RAG health
endpoint honestly surfaces parity, orphans, duplicates, and gaps."""

from datetime import date, datetime, timezone

import pytest

from app.models import GA4SessionsDaily, GSCPerformanceDaily, Property, Upload
from app.models.uploads import SourceType, UploadStatus
from app.services.reporting import DataState
from app.services.reporting_content_impact import (
    EXTERNAL_FACTORS_CAVEAT,
    build_content_impact_report,
)

# "Today" well after both windows so before/after are complete.
TODAY = date(2026, 9, 1)
CHANGE_DATE = date(2026, 6, 15)
_CAUSAL = ["caused", "because of", "led to", "drove", "resulted in", "thanks to"]


def _prop(db, name="Impact Court"):
    p = Property(name=name, slug=name.lower().replace(" ", "-"), city="Denver", state="CO")
    db.add(p)
    db.commit()
    return p


def _upload(db, pid, source):
    u = Upload(
        source_type=source, property_id=pid, filename="seed.csv",
        status=UploadStatus.PROCESSED, row_count=1,
    )
    db.add(u)
    db.commit()
    return u


def _gsc(db, pid, upload_id, d, clicks, impressions):
    db.add(GSCPerformanceDaily(
        property_id=pid, upload_id=upload_id, date=d, query="q", page="/p",
        clicks=clicks, impressions=impressions, ctr=0.0, position=5.0,
    ))
    db.commit()


def _ga4(db, pid, upload_id, d, sessions, medium="organic"):
    db.add(GA4SessionsDaily(
        property_id=pid, upload_id=upload_id, date=d, session_source="google",
        session_medium=medium, sessions=sessions, engaged_sessions=sessions,
        total_users=sessions, key_events=1,
    ))
    db.commit()


def _change(client, pid, title="Expanded FAQ", ctype="faq_update", when="2026-06-15"):
    res = client.post(f"/api/content-changes/{pid}", json={
        "change_title": title, "change_type": ctype, "date_implemented": when,
        "page_url": "/faq",
    })
    assert res.status_code == 201, res.text
    return res.json()


# --- change log CRUD ---------------------------------------------------------


def test_change_crud_and_isolation(client, db):
    p = _prop(db)
    other = _prop(db, "Other Court")
    created = _change(client, p.id)
    cid = created["id"]
    assert created["company_id"] is None
    listed = client.get(f"/api/content-changes/{p.id}").json()
    assert len(listed) == 1

    # A change is scoped to its property: the other property sees none, and
    # cross-property update/delete 404s.
    assert client.get(f"/api/content-changes/{other.id}").json() == []
    assert client.delete(f"/api/content-changes/{other.id}/{cid}").status_code == 404

    upd = client.put(f"/api/content-changes/{p.id}/{cid}", json={
        "change_title": "Expanded FAQ v2", "change_type": "faq_update",
        "date_implemented": "2026-06-16",
    })
    assert upd.status_code == 200 and upd.json()["change_title"] == "Expanded FAQ v2"
    assert client.delete(f"/api/content-changes/{p.id}/{cid}").status_code == 200
    assert client.get(f"/api/content-changes/{p.id}").json() == []


def test_change_requires_title(client, db):
    p = _prop(db)
    res = client.post(f"/api/content-changes/{p.id}", json={
        "change_title": "   ", "change_type": "other", "date_implemented": "2026-06-15",
    })
    assert res.status_code == 422


def test_change_unknown_property_404s(client):
    assert client.post("/api/content-changes/999", json={
        "change_title": "x", "change_type": "other", "date_implemented": "2026-06-15",
    }).status_code == 404


# --- before/after math -------------------------------------------------------


def test_before_after_observed_delta(client, db):
    p = _prop(db)
    gu = _upload(db, p.id, SourceType.GSC).id
    au = _upload(db, p.id, SourceType.GA4).id
    # Before window (30d): 10 clicks total. After window: 25 clicks total.
    _gsc(db, p.id, gu, date(2026, 6, 1), 10, 100)   # before
    _gsc(db, p.id, gu, date(2026, 6, 20), 25, 100)  # after
    _ga4(db, p.id, au, date(2026, 6, 1), 40)        # before
    _ga4(db, p.id, au, date(2026, 6, 20), 70)       # after
    _change(client, p.id)

    report = build_content_impact_report(db, p.id, window=30, today=TODAY)
    assert report["has_changes"] is True
    metrics = {m["key"]: m for m in report["changes"][0]["comparison"]["metrics"]}
    assert metrics["clicks"]["before"] == 10
    assert metrics["clicks"]["after"] == 25
    assert metrics["clicks"]["comparison"]["change"] == 15
    assert metrics["sessions"]["before"] == 40
    assert metrics["sessions"]["after"] == 70
    assert report["changes"][0]["comparison"]["after_complete"] is True


def test_incomplete_after_window_is_disclosed_not_zero(client, db):
    p = _prop(db)
    gu = _upload(db, p.id, SourceType.GSC).id
    _gsc(db, p.id, gu, date(2026, 6, 1), 10, 100)  # before only
    _change(client, p.id)
    # today is only 5 days after the change: the after window is incomplete.
    report = build_content_impact_report(db, p.id, window=30, today=date(2026, 6, 20))
    cmp = report["changes"][0]["comparison"]
    assert cmp["after_complete"] is False
    assert 0 < cmp["after_days_elapsed"] < 30
    clicks = next(m for m in cmp["metrics"] if m["key"] == "clicks")
    # After has no data yet, but 'before' is real; the after value is null, not 0.
    assert clicks["before"] == 10
    assert clicks["after"] is None
    assert clicks["state"] == DataState.PARTIAL_PERIOD.value


def test_caveat_denies_causation_on_every_comparison(client, db):
    p = _prop(db)
    _change(client, p.id)
    report = build_content_impact_report(db, p.id, window=30, today=TODAY)
    # The caveat explicitly DENIES causation (it names external factors and
    # says Beacon does not claim the change caused the result).
    assert report["caveat"] == EXTERNAL_FACTORS_CAVEAT
    assert "does not claim the content change caused" in report["caveat"]
    assert "—" not in report["caveat"]
    # Every change's comparison carries the same denial, and the only prose in
    # the report is metric labels (no generated causal narrative).
    for change in report["changes"]:
        assert change["comparison"]["caveat"] == EXTERNAL_FACTORS_CAVEAT
        for m in change["comparison"]["metrics"]:
            label = m["label"].lower()
            for verb in _CAUSAL:
                assert verb not in label


def test_timeline_lists_changes(client, db):
    p = _prop(db)
    _change(client, p.id, title="A", when="2026-05-01")
    _change(client, p.id, title="B", when="2026-06-01")
    report = build_content_impact_report(db, p.id, window=30, today=TODAY)
    dates = [t["date"] for t in report["timeline"]]
    assert dates == ["2026-05-01", "2026-06-01"]  # chronological


# --- endpoint + CSV ----------------------------------------------------------


def test_content_impact_endpoint_and_csv(client, db):
    p = _prop(db)
    _change(client, p.id)
    r = client.get(f"/api/reports/content-impact?property_id={p.id}&window=30")
    assert r.status_code == 200 and r.json()["has_changes"] is True

    csv = client.get(f"/api/reports/content-impact/export.csv?property_id={p.id}")
    assert csv.status_code == 200
    text = csv.text
    assert EXTERNAL_FACTORS_CAVEAT in text
    for forbidden in ["chunk_id", "vector", "similarity", "embedding", "latency"]:
        assert forbidden not in text.lower()


def test_content_impact_portfolio_scope_requires_property(db):
    assert build_content_impact_report(db, None)["scope_required"] is True


def test_meta_marks_content_impact_available(client):
    tabs = {t["key"]: t for t in client.get("/api/reports/meta").json()["tabs"]}
    assert tabs["content-impact"]["status"] == "available"


# --- RAG index health --------------------------------------------------------


def test_rag_health_reports_structure(client, db):
    body = client.get("/api/admin/rag-health").json()
    for key in [
        "total_indexed_chunks", "registry_chunks", "parity_ok",
        "chunks_by_source", "orphans", "duplicate_content_hashes",
        "stale_pre_enrichment_chunks", "properties_with_content_not_indexed",
        "configured_sources_not_indexed", "embedding_model", "index_version",
    ]:
        assert key in body, key
    assert "registered_without_vector" in body["orphans"]
    assert "vector_without_record" in body["orphans"]


def test_rag_health_detects_duplicate_hashes(client, db):
    from app.models import RAGChunk

    p = _prop(db)
    # Two registry rows sharing a text hash = duplicate content.
    db.add_all([
        RAGChunk(chroma_id="a1", property_id=p.id, source_table="content",
                 source_ref="r1", text_hash="deadbeef", source="content"),
        RAGChunk(chroma_id="a2", property_id=p.id, source_table="content",
                 source_ref="r2", text_hash="deadbeef", source="content"),
    ])
    db.commit()
    body = client.get("/api/admin/rag-health").json()
    dupes = {d["text_hash"]: d["count"] for d in body["duplicate_content_hashes"]}
    assert dupes.get("deadbeef") == 2


def test_retrieval_debug_exposes_latency_and_index_version(client, db, tmp_path, monkeypatch):
    # Deterministic embedder in tests; the debug view is admin-only and carries
    # latency + index version (never in any client report).
    from app.config import settings

    monkeypatch.setattr(settings, "demo_mode", True)
    monkeypatch.setattr(settings, "chroma_dir", str(tmp_path / "chroma"))
    body = client.get("/api/admin/retrieval-debug?q=parking").json()
    assert "retrieval_latency_ms" in body
    assert "index_version" in body
    assert "embedding_model" in body
