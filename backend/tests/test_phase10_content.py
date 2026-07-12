"""Content storage, the content endpoints, the ContentProvider connector, and
content + Content Intelligence chunks flowing into RAG."""

from datetime import datetime, timezone

from app.connectors.development import DevelopmentDataProvider
from app.models import PropertyContent, RAGChunk, RagSyncJob
from app.providers.development import DeterministicEmbeddingProvider
from app.services.rag.indexer import build_index
from tests.test_phase2_uploads import make_property


def put_content(client, property_id, page, body, **kw):
    payload = {"page": page, "title": kw.get("title", page.title()), "body": body}
    payload.update({k: v for k, v in kw.items() if k != "title"})
    return client.put(f"/api/content/{property_id}", json=payload)


def test_upsert_and_list_content(client, db):
    prop = make_property(client, "Content Property")
    resp = put_content(
        client, prop["id"], "homepage", "Resort-style pool and fitness center.",
        mapped_keyword="apartments in tempe az",
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["mapped_keyword"] == "apartments in tempe az"

    # Upsert (same page) updates in place.
    put_content(client, prop["id"], "homepage", "Updated copy with a pool.")
    pages = client.get(f"/api/content/{prop['id']}").json()
    assert len(pages) == 1
    assert "Updated copy" in pages[0]["body"]


def test_invalid_page_rejected(client):
    prop = make_property(client, "Bad Page Property")
    resp = put_content(client, prop["id"], "pricing", "x")
    assert resp.status_code == 422
    assert "page must be one of" in resp.json()["detail"]


def test_content_edit_enqueues_sync(client, db):
    prop = make_property(client, "Sync On Edit")
    put_content(client, prop["id"], "homepage", "A pool and a gym.")
    job = db.query(RagSyncJob).order_by(RagSyncJob.id.desc()).first()
    assert job.source == "content"
    assert job.reason == "content_edit"


def test_connector_returns_content_records(client, db):
    prop = make_property(client, "Connector Content")
    put_content(
        client, prop["id"], "amenities", "Stainless steel and quartz counters.",
        mapped_keyword="luxury amenities",
    )
    records = DevelopmentDataProvider().get_content(db, prop["id"])
    assert len(records) == 1
    assert records[0].page == "amenities"
    assert records[0].mapped_keyword == "luxury amenities"


def test_content_and_ci_chunks_indexed(client, db, tmp_path):
    prop = make_property(client, "Indexed Content")
    put_content(
        client, prop["id"], "homepage",
        "Located in Tempe near ASU. Resort-style pool, 24-hour fitness center. "
        "Studio and one bedroom floor plans starting at $1,400. Schedule a tour.",
        mapped_keyword="apartments in tempe az",
    )
    build_index(db, DeterministicEmbeddingProvider(), str(tmp_path / "chroma"))

    sources = {r.source for r in db.query(RAGChunk).filter_by(property_id=prop["id"]).all()}
    assert "content" in sources
    assert "content_intelligence" in sources
    content_row = db.query(RAGChunk).filter_by(source="content").first()
    assert content_row.page == "homepage"
    ci_row = db.query(RAGChunk).filter_by(source="content_intelligence").first()
    assert ci_row.chroma_id == f"content_intelligence-p{prop['id']}"
