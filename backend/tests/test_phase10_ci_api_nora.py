"""Content Intelligence API endpoints and Nora answering content questions from
the Content Intelligence chunk with citations."""

from app.models import RagSyncJob
from app.providers.development import DeterministicEmbeddingProvider
from app.services import nora
from app.services.rag.indexer import build_index
from tests.test_phase2_uploads import make_property
from tests.test_phase8_nora import FakeLLM
from tests.test_phase10_content import put_content


def seed_property_content(client, name="CI Nora Property"):
    prop = make_property(client, name)
    put_content(
        client, prop["id"], "homepage",
        "Located in Tempe near ASU. Resort-style pool and 24-hour fitness center. "
        "Studio and one bedroom floor plans starting at $1,400. Schedule a tour.",
        mapped_keyword="apartments in tempe az",
    )
    put_content(
        client, prop["id"], "neighborhood",
        "Near Tempe Marketplace shopping and restaurants.",
    )
    return prop


# --- API ---


def test_get_analysis_endpoint(client):
    prop = seed_property_content(client)
    body = client.get(f"/api/content-intelligence/{prop['id']}").json()
    assert body["has_content"] is True
    assert body["score"]["value"] >= 0
    assert body["question_coverage"]["summary"]["total"] == 16
    assert body["neighborhood"]["rating"] in ("Poor", "Basic", "Good", "Excellent")


def test_analyze_endpoint_enqueues_refresh(client, db):
    prop = seed_property_content(client)
    resp = client.post(f"/api/content-intelligence/{prop['id']}/analyze")
    assert resp.status_code == 200
    body = resp.json()
    assert body["analysis"]["has_content"] is True
    assert body["sync_job_id"] is not None
    job = db.query(RagSyncJob).filter_by(id=body["sync_job_id"]).one()
    assert job.source == "content"


def test_unknown_property_404(client):
    assert client.get("/api/content-intelligence/999").status_code == 404


# --- Nora integration ---


def test_nora_answers_content_question_with_ci_citation(client, db, tmp_path):
    prop = seed_property_content(client)
    chroma_dir = str(tmp_path / "chroma")
    build_index(db, DeterministicEmbeddingProvider(), chroma_dir)

    result = nora.ask(
        db,
        "What content should we improve first?",
        FakeLLM(reply="Focus on the biggest gaps [1]."),
        DeterministicEmbeddingProvider(),
        property_id=prop["id"],
        chroma_dir=chroma_dir,
    )
    tables = {c["source_table"] for c in result["citations"]}
    assert "content_intelligence" in tables


def test_nora_retrieves_missing_questions(client, db, tmp_path):
    prop = seed_property_content(client)
    chroma_dir = str(tmp_path / "chroma")
    build_index(db, DeterministicEmbeddingProvider(), chroma_dir)

    result = nora.ask(
        db,
        "What renter questions are missing from our website?",
        FakeLLM(),
        DeterministicEmbeddingProvider(),
        property_id=prop["id"],
        chroma_dir=chroma_dir,
    )
    # The CI chunk (which lists missing questions) is among the retrieved sources.
    refs = " ".join(c["source_ref"] for c in result["citations"])
    assert "content_intelligence" in refs
