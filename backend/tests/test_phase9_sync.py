"""Automatic RAG sync: registry lineage, incremental scoped sync, queue
processing, provider-change full rebuild, content chunks via connector, hooks."""

import pytest

from app.connectors.development import DevelopmentDataProvider
from app.models import RAGChunk, RagSyncJob, RagSyncStatus
from app.providers.development import DeterministicEmbeddingProvider
from app.services.rag.chunker import build_chunks
from app.services.rag.indexer import build_index
from app.services.rag_sync_service import (
    drain_queue,
    enqueue_sync,
    process_job,
)
from tests.test_phase2_uploads import make_property, post_upload
from tests.test_phase5_crm import post_crm
from tests.test_phase9_connectors import FakeContentProvider


@pytest.fixture()
def chroma_dir(tmp_path):
    return str(tmp_path / "chroma")


@pytest.fixture()
def seeded(client, db):
    prop = make_property(client, "Solara Flats")
    post_upload(client, "ga4", prop["id"], "ga4_traffic_with_date.csv")
    post_crm(client, prop["id"], "crm_yardi_placeholder.csv")
    # Uploads auto-enqueue sync jobs (covered separately); clear them so each
    # test controls its own queue deterministically.
    db.query(RagSyncJob).delete()
    db.commit()
    return prop


# --- registry lineage (Objective 5) ---


def test_index_populates_registry_lineage(seeded, db, chroma_dir):
    provider = DeterministicEmbeddingProvider()
    build_index(db, provider, chroma_dir)
    ga4 = db.query(RAGChunk).filter_by(source="ga4").one()
    assert ga4.provider == "deterministic"
    assert ga4.embedding_version == "v1"
    assert ga4.page is None
    assert ga4.updated_at is not None
    crm = db.query(RAGChunk).filter_by(source="crm").one()
    assert crm.source_table == "crm_leads"


def test_content_chunks_carry_page(db, client):
    prop = make_property(client, "Content Property")
    chunks = build_chunks(db, content_provider=FakeContentProvider())
    content = [c for c in chunks if c.source == "content"]
    assert len(content) == 1
    assert content[0].page == "homepage"
    assert content[0].chroma_id == f"content-p{prop['id']}-homepage"


# --- queue architecture (Objective 2) ---


def test_enqueue_creates_queued_job(seeded, db):
    job = enqueue_sync(db, property_id=seeded["id"], source="ga4", reason="ga4_import")
    assert job.status == RagSyncStatus.QUEUED
    assert job.property_id == seeded["id"]
    assert job.chunks_embedded == 0


def test_upload_enqueues_without_embedding(client, db):
    prop = make_property(client, "Queue Property")
    resp = post_upload(client, "ga4", prop["id"], "ga4_traffic_with_date.csv")
    body = resp.json()
    # UI got a fast response with a job id; no embeddings ran inline.
    assert body["sync_job_id"] is not None
    job = db.query(RagSyncJob).filter_by(id=body["sync_job_id"]).one()
    assert job.status == RagSyncStatus.QUEUED
    assert db.query(RAGChunk).count() == 0  # nothing embedded yet


# --- incremental sync (Objective 1) ---


def test_drain_processes_queue_incrementally(seeded, db, chroma_dir):
    provider = DeterministicEmbeddingProvider()
    enqueue_sync(db, property_id=seeded["id"], source="ga4", reason="ga4_import")
    result = drain_queue(db=db, provider=provider, chroma_dir=chroma_dir)
    assert result == {"processed": 1, "failed": 0}

    job = db.query(RagSyncJob).order_by(RagSyncJob.id.desc()).first()
    assert job.status == RagSyncStatus.COMPLETED
    # GA4 chunk + its derived AI Query Signals chunk + the Opportunity Engine
    # chunk (a ga4 sync widens to both).
    assert job.chunks_embedded == 3
    assert db.query(RAGChunk).filter_by(source="ga4").count() == 1
    assert db.query(RAGChunk).filter_by(source="ai_query_signals").count() == 1
    assert db.query(RAGChunk).filter_by(source="opportunity_engine").count() == 1
    # CRM was not in scope, so no CRM chunk was created by this job.
    assert db.query(RAGChunk).filter_by(source="crm").count() == 0


def test_scoped_sync_does_not_touch_other_properties(client, db, chroma_dir):
    a = make_property(client, "Alpha")
    b = make_property(client, "Beta")
    post_upload(client, "ga4", a["id"], "ga4_traffic_with_date.csv")
    post_upload(client, "ga4", b["id"], "ga4_combined_source_medium.csv")
    provider = DeterministicEmbeddingProvider()

    # Index everything first. Each property with AI traffic yields a GA4 chunk,
    # a derived AI Query Signals chunk, and an Opportunity Engine chunk
    # (2 properties x 3 = 6).
    build_index(db, provider, chroma_dir)
    assert db.query(RAGChunk).count() == 6

    # Re-upload only A, then sync only A's scope.
    post_upload(client, "ga4", a["id"], "ga4_multi_ai.csv")
    job = enqueue_sync(db, property_id=a["id"], source="ga4", reason="ga4_import")
    process_job(db, job, provider, chroma_dir)
    # A's GA4 + AI Query Signals chunks re-embedded; the Opportunity Engine
    # chunk is in scope but its text did not change, so it is not re-embedded.
    assert job.chunks_embedded == 2
    # B's chunks untouched and still present (GA4 + AI Query Signals + Opportunity).
    assert db.query(RAGChunk).filter_by(property_id=b["id"]).count() == 3


def test_provider_change_forces_full_rebuild(seeded, db, chroma_dir):
    # Index with the 128-dim provider.
    build_index(db, DeterministicEmbeddingProvider(dims=128), chroma_dir)
    total = db.query(RAGChunk).count()
    assert total >= 2

    # A different embedding version (simulated via a different dim/version) must
    # re-embed everything even for a scoped job.
    new_provider = DeterministicEmbeddingProvider(dims=64)
    new_provider.version = "v2"
    job = enqueue_sync(db, property_id=seeded["id"], source="ga4", reason="ga4_import")
    process_job(db, job, new_provider, chroma_dir)
    assert job.chunks_embedded == total  # full rebuild, not just the scoped chunk
    assert all(r.embedding_version == "v2" for r in db.query(RAGChunk).all())


def test_drain_without_provider_fails_jobs_readably(seeded, db, chroma_dir, monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "demo_mode", False)
    monkeypatch.setattr(settings, "openai_api_key", "")
    enqueue_sync(db, property_id=seeded["id"], source="ga4", reason="ga4_import")
    result = drain_queue(db=db, chroma_dir=chroma_dir)
    assert result == {"processed": 0, "failed": 1}
    job = db.query(RagSyncJob).order_by(RagSyncJob.id.desc()).first()
    assert job.status == RagSyncStatus.FAILED
    assert "BEACON_OPENAI_API_KEY" in job.error_message


# --- future hooks (Objective 7) ---


def test_trigger_rag_sync_hook_enqueues(seeded, db):
    from app.extensions.hooks import trigger_rag_sync

    job = trigger_rag_sync(db, property_id=seeded["id"], source="ga4", reason="test")
    assert job.status == RagSyncStatus.QUEUED


def test_intelligence_module_can_request_reindex_without_touching_services(seeded, db):
    from app.extensions.hooks import IntelligenceModule

    class DummyScanner(IntelligenceModule):
        name = "dummy_scanner"

        def on_data_change(self, db, property_id=None, source=None):
            self.request_reindex(db, property_id=property_id, source=source)

    scanner = DummyScanner()
    scanner.on_data_change(db, property_id=seeded["id"], source="ga4")
    job = db.query(RagSyncJob).order_by(RagSyncJob.id.desc()).first()
    assert job.reason == "module:dummy_scanner"
    assert job.status == RagSyncStatus.QUEUED
