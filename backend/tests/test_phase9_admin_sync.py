"""Synchronization dashboard endpoints (Objective 6) and process-queue."""

import pytest

from app.models import RAGChunk
from tests.test_phase2_uploads import make_property, post_upload


@pytest.fixture()
def demo(monkeypatch, tmp_path):
    from app.config import settings

    monkeypatch.setattr(settings, "demo_mode", True)
    monkeypatch.setattr(settings, "chroma_dir", str(tmp_path / "chroma"))
    return settings


def test_status_reports_providers(demo, client):
    body = client.get("/api/admin/status").json()
    assert body["embedding_provider"].startswith("deterministic")
    assert body["llm_provider"].startswith("demo")


def test_sync_status_shape(demo, client):
    body = client.get("/api/admin/sync-status").json()
    for key in (
        "last_sync",
        "chunks_indexed",
        "chunks_updated_today",
        "queued_jobs",
        "failed_jobs",
        "embedding_provider",
        "llm_provider",
        "last_rebuild",
        "recent_jobs",
    ):
        assert key in body


def test_upload_then_process_queue_updates_kb(demo, client, db):
    prop = make_property(client, "KB Property")
    resp = post_upload(client, "ga4", prop["id"], "ga4_traffic_with_date.csv")
    assert resp.json()["sync_job_id"] is not None

    before = client.get("/api/admin/sync-status").json()
    assert before["queued_jobs"] == 1
    assert before["chunks_indexed"] in (0, None)

    processed = client.post("/api/admin/process-queue").json()
    assert processed["status"] == "ok"
    assert processed["processed"] == 1

    after = client.get("/api/admin/sync-status").json()
    assert after["queued_jobs"] == 0
    # GA4 chunk + derived AI Query Signals chunk + Opportunity Engine chunk.
    assert after["chunks_indexed"] == 3
    assert after["chunks_updated_today"] == 3
    assert after["last_sync"] is not None
    assert after["recent_jobs"][0]["status"] == "completed"
    # Registry reflects the sync.
    assert db.query(RAGChunk).filter_by(source="ga4").count() == 1
