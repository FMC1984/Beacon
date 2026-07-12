"""Review Intelligence API, RAG indexing, stale-chunk cleanup, and Nora
answering review questions with citations, honesty, and context compliance."""

from app.models import RAGChunk
from app.providers.development import DeterministicEmbeddingProvider
from app.services import nora
from app.services.rag.indexer import build_index
from tests.test_phase2_uploads import make_property
from tests.test_phase8_nora import FakeLLM
from tests.test_phase11_reviews import create_review
from tests.test_phase105_context_api import put_ctx


def seed_reviews(client, property_id):
    create_review(client, property_id, rating=5, title="Love it", body="Friendly staff and clean.", review_date="2026-06-01")
    create_review(client, property_id, rating=2, title="Parking", body="Maintenance never fixed my heater, parking is terrible.", review_date="2026-06-02")
    create_review(client, property_id, rating=1, title="Roaches", body="Infestation of roaches, do not move here.", review_date="2026-06-03")


# --- API ---


def test_get_and_analyze_endpoints(client, db):
    prop = make_property(client, "RI API")
    seed_reviews(client, prop["id"])
    body = client.get(f"/api/review-intelligence/{prop['id']}").json()
    assert body["has_reviews"] is True
    assert body["score"]["value"] >= 0
    resp = client.post(f"/api/review-intelligence/{prop['id']}/analyze")
    assert resp.status_code == 200
    assert resp.json()["sync_job_id"] is not None


def test_empty_review_intelligence(client, db):
    prop = make_property(client, "RI Empty")
    body = client.get(f"/api/review-intelligence/{prop['id']}").json()
    assert body["has_reviews"] is False


# --- RAG indexing + cleanup ---


def test_review_and_ri_chunks_indexed(client, db, tmp_path):
    prop = make_property(client, "RI Chunks")
    seed_reviews(client, prop["id"])
    build_index(db, DeterministicEmbeddingProvider(), str(tmp_path / "chroma"))
    sources = {r.source for r in db.query(RAGChunk).filter_by(property_id=prop["id"]).all()}
    assert "reviews" in sources
    assert "review_intelligence" in sources
    # One chunk per review (citation fidelity).
    assert db.query(RAGChunk).filter_by(source="reviews", property_id=prop["id"]).count() == 3


def test_deleted_review_chunk_removed(client, db, tmp_path):
    prop = make_property(client, "RI Cleanup")
    seed_reviews(client, prop["id"])
    chroma_dir = str(tmp_path / "chroma")
    build_index(db, DeterministicEmbeddingProvider(), chroma_dir)
    review_id = client.get(f"/api/reviews/{prop['id']}").json()[0]["id"]

    client.delete(f"/api/reviews/{prop['id']}/{review_id}")
    build_index(db, DeterministicEmbeddingProvider(), chroma_dir)

    remaining = {
        r.chroma_id for r in db.query(RAGChunk).filter_by(source="reviews", property_id=prop["id"]).all()
    }
    assert f"review-p{prop['id']}-{review_id}" not in remaining
    assert db.query(RAGChunk).filter_by(source="reviews", property_id=prop["id"]).count() == 2


# --- Nora ---


def ask(db, question, property_id, chroma_dir, reply="Answer [1]."):
    return nora.ask(
        db, question, FakeLLM(reply=reply), DeterministicEmbeddingProvider(),
        property_id=property_id, chroma_dir=chroma_dir,
    )


def test_nora_answers_complaints_with_citation(client, db, tmp_path):
    prop = make_property(client, "Nora Complaints")
    seed_reviews(client, prop["id"])
    chroma_dir = str(tmp_path / "chroma")
    build_index(db, DeterministicEmbeddingProvider(), chroma_dir)
    result = ask(db, "What are residents complaining about most?", prop["id"], chroma_dir)
    tables = {c["source_table"] for c in result["citations"]}
    assert "review_intelligence" in tables or "property_reviews" in tables


def test_nora_marketing_themes_question(client, db, tmp_path):
    prop = make_property(client, "Nora Marketing")
    seed_reviews(client, prop["id"])
    chroma_dir = str(tmp_path / "chroma")
    build_index(db, DeterministicEmbeddingProvider(), chroma_dir)
    result = ask(db, "What positive review themes should we use in marketing?", prop["id"], chroma_dir)
    assert result["citations"]


def test_nora_regulated_marketing_respects_context(client, db, tmp_path):
    prop = make_property(client, "Nora Regulated")
    put_ctx(client, prop["id"], property_type="affordable", is_regulated=True,
            regulatory_programs=["LIHTC"])
    seed_reviews(client, prop["id"])
    chroma_dir = str(tmp_path / "chroma")
    build_index(db, DeterministicEmbeddingProvider(), chroma_dir)
    # The review_intelligence chunk states the restrictions verbatim, so Nora
    # retrieves compliance context for a marketing question.
    result = ask(db, "What marketing themes should we use from our reviews?", prop["id"], chroma_dir)
    ri = next((c for c in result["citations"] if c["source_table"] == "review_intelligence"), None)
    assert ri is not None


def test_nora_cannot_cite_deleted_review(client, db, tmp_path):
    prop = make_property(client, "Nora Deleted")
    seed_reviews(client, prop["id"])
    chroma_dir = str(tmp_path / "chroma")
    build_index(db, DeterministicEmbeddingProvider(), chroma_dir)
    review_id = client.get(f"/api/reviews/{prop['id']}").json()[0]["id"]
    client.delete(f"/api/reviews/{prop['id']}/{review_id}")
    build_index(db, DeterministicEmbeddingProvider(), chroma_dir)

    result = ask(db, "Show me resident reviews.", prop["id"], chroma_dir, reply="Reviews [1].")
    cited_ids = {c.get("source_ref", "") for c in result["citations"]}
    assert not any(f"review_id={review_id}," in ref for ref in cited_ids)
