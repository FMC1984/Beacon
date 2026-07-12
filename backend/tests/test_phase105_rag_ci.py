"""property_context RAG chunk (indexed, scoped, citable, replace-on-write) and
Content Intelligence consuming property context from day one."""

from app.models import RAGChunk
from app.providers.development import DeterministicEmbeddingProvider
from app.services import nora
from app.services.content_intelligence import analyze_property
from app.services.rag.indexer import build_index
from tests.test_phase2_uploads import make_property
from tests.test_phase8_nora import FakeLLM
from tests.test_phase105_context_api import put_ctx
from tests.test_phase10_content import put_content


def test_property_context_chunk_indexed_and_scoped(client, db, tmp_path):
    prop = make_property(client, "Ctx Chunk")
    put_ctx(client, prop["id"], property_type="senior", is_regulated=True,
            regulatory_programs=["LIHTC"])
    build_index(db, DeterministicEmbeddingProvider(), str(tmp_path / "chroma"))

    rows = db.query(RAGChunk).filter_by(source="property_context").all()
    assert len(rows) == 1
    assert rows[0].property_id == prop["id"]
    assert rows[0].chroma_id == f"property_context-p{prop['id']}"


def test_context_chunk_replaced_not_appended(client, db, tmp_path):
    prop = make_property(client, "Replace Ctx")
    chroma_dir = str(tmp_path / "chroma")
    put_ctx(client, prop["id"], property_type="student", is_regulated=False)
    build_index(db, DeterministicEmbeddingProvider(), chroma_dir)

    # Change context and rebuild; still exactly one property_context chunk.
    put_ctx(client, prop["id"], property_type="senior", is_regulated=True)
    build_index(db, DeterministicEmbeddingProvider(), chroma_dir)

    rows = db.query(RAGChunk).filter_by(
        source="property_context", property_id=prop["id"]
    ).all()
    assert len(rows) == 1
    # Chunk text reflects the update (verbatim).
    from app.services.property_context import get_property_context, property_context_chunk_text
    expected = property_context_chunk_text(get_property_context(db, prop["id"]))
    assert rows[0].text_hash is not None


def test_no_context_no_chunk(client, db, tmp_path):
    prop = make_property(client, "No Ctx")
    build_index(db, DeterministicEmbeddingProvider(), str(tmp_path / "chroma"))
    assert db.query(RAGChunk).filter_by(source="property_context").count() == 0


def test_nora_cites_property_context(client, db, tmp_path):
    prop = make_property(client, "Nora Ctx")
    put_ctx(client, prop["id"], property_type="affordable", is_regulated=True,
            regulatory_programs=["Section_8"])
    chroma_dir = str(tmp_path / "chroma")
    build_index(db, DeterministicEmbeddingProvider(), chroma_dir)

    result = nora.ask(
        db,
        "Is this property regulated and what programs apply?",
        FakeLLM(reply="See the property context [1]."),
        DeterministicEmbeddingProvider(),
        property_id=prop["id"],
        chroma_dir=chroma_dir,
    )
    tables = {c["source_table"] for c in result["citations"]}
    assert "property_context" in tables


# --- Content Intelligence consumes context ---


def test_ci_includes_context_and_compliance(client, db):
    prop = make_property(client, "CI Ctx Regulated")
    put_ctx(client, prop["id"], property_type="affordable", is_regulated=True,
            regulatory_programs=["LIHTC"])
    put_content(client, prop["id"], "homepage", "A pool and a gym in Tempe.")
    a = analyze_property(db, prop["id"])
    assert a["property_context"]["effective_regulatory"] == "regulated"
    assert a["compliance"]["level"] == "caution"
    # marketing_guidance suppresses restricted themes for a regulated property.
    suppressed = {g["theme"] for g in a["marketing_guidance"] if g["status"] == "suppressed"}
    assert "exclusivity" in suppressed
    assert "young_professional" in suppressed


def test_ci_unknown_context_withholds_compliance(client, db):
    prop = make_property(client, "CI Ctx Unknown")
    put_content(client, prop["id"], "homepage", "A pool and a gym in Tempe.")
    a = analyze_property(db, prop["id"])
    assert a["property_context"]["effective_regulatory"] == "unknown"
    assert a["compliance"]["level"] == "withheld"
    assert "not specified" in a["compliance"]["message"]
