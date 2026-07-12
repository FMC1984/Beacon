"""Cascading property delete: removes all child rows, uploaded files, and RAG
chunks/vectors for the property, and leaves other properties untouched."""

from pathlib import Path

from app.models import CRMLead, GA4SessionsDaily, RAGChunk, Upload
from app.providers.development import DeterministicEmbeddingProvider
from app.services.rag.indexer import build_index
from tests.test_phase105_context_api import put_ctx
from tests.test_phase11_reviews import create_review
from tests.test_phase2_uploads import make_property, post_upload
from tests.test_phase5_crm import post_crm
from tests.test_phase10_content import put_content


def test_delete_cascades_all_child_rows(client, db, tmp_path):
    prop = make_property(client, "Delete Me")
    other = make_property(client, "Keep Me")

    post_upload(client, "ga4", prop["id"], "ga4_traffic_with_date.csv")
    post_crm(client, prop["id"], "crm_yardi_placeholder.csv")
    put_content(client, prop["id"], "homepage", "A pool and a gym in Tempe.")
    put_ctx(client, prop["id"], property_type="conventional", is_regulated=False)
    create_review(client, prop["id"], rating=4, body="Nice place.")
    post_upload(client, "ga4", other["id"], "ga4_combined_source_medium.csv")

    build_index(db, DeterministicEmbeddingProvider(), str(tmp_path / "chroma"))

    resp = client.delete(f"/api/properties/{prop['id']}")
    assert resp.status_code == 200, resp.text

    assert db.query(GA4SessionsDaily).filter_by(property_id=prop["id"]).count() == 0
    assert db.query(CRMLead).filter_by(property_id=prop["id"]).count() == 0
    assert db.query(Upload).filter_by(property_id=prop["id"]).count() == 0
    assert db.query(RAGChunk).filter_by(property_id=prop["id"]).count() == 0
    assert client.get(f"/api/properties/{prop['id']}").status_code == 404

    # Other property's data survives untouched.
    assert db.query(GA4SessionsDaily).filter_by(property_id=other["id"]).count() == 2
    assert client.get(f"/api/properties/{other['id']}").status_code == 200


def test_delete_removes_stored_upload_files(client, db):
    prop = make_property(client, "File Cleanup")
    resp = post_upload(client, "ga4", prop["id"], "ga4_traffic_with_date.csv")
    upload = db.query(Upload).filter_by(id=resp.json()["upload_id"]).one()
    stored = Path(upload.stored_path)
    assert stored.exists()

    client.delete(f"/api/properties/{prop['id']}")
    assert not stored.exists()


def test_delete_unknown_property_404(client):
    assert client.delete("/api/properties/999").status_code == 404
