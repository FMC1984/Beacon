"""Phase 18C: Share of Voice RAG chunk. Deterministic summary chunk text,
honest absence without competitor/sample data, refreshed when AI Visibility
or Competitor data changes (the widen list), and retrievable by the hybrid
retriever so Nora can ground Share of Voice answers."""

from datetime import datetime, timezone

from app.connectors.base import AIVisibilityQueryProvider
from app.models import AITopic, AIVisibilityPrompt, Competitor, Property
from app.services.ai_visibility import run_query
from app.services.rag.chunker import build_chunks
from app.services.reporting_share_of_voice import share_of_voice_summary_text


class FR(AIVisibilityQueryProvider):
    def __init__(self, response):
        self.response = response

    def execute_query(self, prompt, platform):
        return self.response

    def get_queries(self, db, property_id):
        return []


TODAY = datetime(2026, 8, 10, 12, 0, tzinfo=timezone.utc)


def _prop(db, name="RAG SoV Court"):
    p = Property(name=name, slug=name.lower().replace(" ", "-"))
    db.add(p)
    db.commit()
    return p


def _seed_sufficient(db, p, topic_name="Amenities"):
    comp = Competitor(property_id=p.id, name="Rival Co")
    db.add(comp)
    db.commit()
    topic = AITopic(property_id=p.id, topic_name=topic_name, priority="high")
    db.add(topic)
    db.commit()
    prompt = AIVisibilityPrompt(
        property_id=p.id, prompt_text="What amenities?", platform="chatgpt",
        topic_id=topic.id,
    )
    db.add(prompt)
    db.commit()
    for _ in range(3):
        run_query(
            db, p.id, "What amenities?", "chatgpt",
            provider=FR(f"{p.name} has a great pool, unlike Rival Co."), now=TODAY,
        )
    return comp, topic


def test_summary_none_without_competitors(db):
    p = _prop(db, "No Competitor Court")
    assert share_of_voice_summary_text(db, p.id) is None


def test_summary_none_below_sample_minimum(db):
    p = _prop(db, "Thin Sample Court")
    comp = Competitor(property_id=p.id, name="Rival Co")
    db.add(comp)
    db.commit()
    run_query(
        db, p.id, "How is the property?", "chatgpt",
        provider=FR("Thin Sample Court is nice."), now=TODAY,
    )
    assert share_of_voice_summary_text(db, p.id) is None


def test_summary_contains_share_topic_and_platform(db):
    p = _prop(db)
    _seed_sufficient(db, p)
    text = share_of_voice_summary_text(db, p.id)
    assert text is not None
    assert "Share of Voice" in text
    assert "Amenities" in text
    assert "ChatGPT" in text
    assert "—" not in text  # no em dashes in copy


def test_chunk_built_and_scoped(db):
    p = _prop(db, "Scoped SoV Court")
    other = _prop(db, "Other SoV Court")
    _seed_sufficient(db, p)

    chunks = build_chunks(db, sources=["share_of_voice"])
    by_prop = {c.property_id: c for c in chunks}
    assert p.id in by_prop and other.id not in by_prop
    c = by_prop[p.id]
    assert c.source == "share_of_voice"
    assert c.chroma_id == f"share_of_voice-p{p.id}"


def test_ai_visibility_sync_widens_to_refresh_share_of_voice(db, monkeypatch, tmp_path):
    captured = {}

    from app.services import rag_sync_service
    from app.services.rag.embedder import DeterministicEmbedder

    def fake_build_chunks(db_, property_id=None, sources=None, **kw):
        captured["sources"] = sources
        return []

    monkeypatch.setattr(rag_sync_service, "build_chunks", fake_build_chunks)
    monkeypatch.setattr(rag_sync_service, "_provider_changed", lambda *a: False)

    p = _prop(db, "Widen SoV Court")
    from app.models import RagSyncJob

    job = RagSyncJob(property_id=p.id, source="ai_visibility", reason="test")
    db.add(job)
    db.commit()
    result = rag_sync_service.drain_queue(
        db=db, provider=DeterministicEmbedder(), chroma_dir=str(tmp_path / "chroma")
    )
    assert result["processed"] == 1, result
    assert "share_of_voice" in (captured.get("sources") or [])
    assert "competitor_intelligence" in (captured.get("sources") or [])


def test_competitors_sync_widens_to_refresh_share_of_voice(db, monkeypatch, tmp_path):
    captured = {}

    from app.services import rag_sync_service
    from app.services.rag.embedder import DeterministicEmbedder

    def fake_build_chunks(db_, property_id=None, sources=None, **kw):
        captured["sources"] = sources
        return []

    monkeypatch.setattr(rag_sync_service, "build_chunks", fake_build_chunks)
    monkeypatch.setattr(rag_sync_service, "_provider_changed", lambda *a: False)

    p = _prop(db, "Widen Comp Court")
    from app.models import RagSyncJob

    job = RagSyncJob(property_id=p.id, source="competitors", reason="test")
    db.add(job)
    db.commit()
    result = rag_sync_service.drain_queue(
        db=db, provider=DeterministicEmbedder(), chroma_dir=str(tmp_path / "chroma")
    )
    assert result["processed"] == 1, result
    assert "share_of_voice" in (captured.get("sources") or [])


def test_chunk_retrievable_by_hybrid_retriever(db, tmp_path):
    from app.services.rag.embedder import DeterministicEmbedder
    from app.services.rag.indexer import build_index
    from app.services.rag.retriever import retrieve

    p = _prop(db, "Retrieval SoV Court")
    _seed_sufficient(db, p)
    chroma_dir = str(tmp_path / "chroma")
    build_index(db, DeterministicEmbedder(), chroma_dir)

    hits = retrieve(
        db, DeterministicEmbedder(), "What is our AI Share of Voice?",
        property_id=p.id, chroma_dir=chroma_dir,
    )
    texts = " ".join(h.text for h in hits)
    assert "Share of Voice" in texts
    assert any(h.citation.source_table == "share_of_voice" for h in hits)
