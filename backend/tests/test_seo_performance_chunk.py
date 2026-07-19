"""SEO Performance RAG chunk (17E follow-up). The briefing's strategic
questions name striking-distance queries; Nora can only answer what the index
contains, so a deterministic summary chunk carries the actual queries with
their metrics. Rules: honest absence without query data, bounded size,
refreshed when GSC/GA4 data changes, retrievable by the hybrid retriever."""

from datetime import date

from app.models.uploads import SourceType
from app.services.rag.chunker import build_chunks
from app.services.reporting_seo import seo_performance_summary_text
from tests.test_phase17b_story import _ga4, _gsc, _prop, _upload


def _seed_striking(db, pid, today_anchor=date(2026, 6, 20)):
    """Queries inside the anchored 30-day window, positions 8-20, enough
    impressions to clear the quadrant threshold."""
    gu = _upload(db, pid, SourceType.GSC)
    _gsc(db, pid, gu, today_anchor, "senior apartments near me", 2, 120, position=11.0)
    _gsc(db, pid, gu, today_anchor, "affordable housing waitlist", 1, 90, position=14.5)
    _gsc(db, pid, gu, today_anchor, "page one query", 30, 200, position=2.0)


def test_summary_contains_actual_queries_with_metrics(db):
    p = _prop(db, "Chunk Court")
    _seed_striking(db, p.id)
    text = seo_performance_summary_text(db, p.id)
    assert text is not None
    # The striking-distance queries appear BY NAME with their metrics.
    assert '"senior apartments near me"' in text
    assert "position 11.0" in text and "120 impressions" in text
    assert '"affordable housing waitlist"' in text
    # A page-one query is not striking distance.
    assert "striking-distance" in text
    # The honest scope note survives.
    assert "not a complete rank-tracking database" in text
    assert "—" not in text  # no em dashes in copy


def test_summary_none_without_query_data(db):
    p = _prop(db, "No Query Court")
    assert seo_performance_summary_text(db, p.id) is None


def test_chunk_built_and_scoped(db):
    p = _prop(db, "Scoped Court")
    other = _prop(db, "Other Court")
    _seed_striking(db, p.id)

    chunks = build_chunks(db, sources=["seo_performance"])
    by_prop = {c.property_id: c for c in chunks}
    # The property with data gets exactly one chunk; the other gets none.
    assert p.id in by_prop and other.id not in by_prop
    c = by_prop[p.id]
    assert c.source == "seo_performance"
    assert c.chroma_id == f"seo_performance-p{p.id}"
    assert "senior apartments near me" in c.text


def test_gsc_sync_widens_to_refresh_seo_performance(db, monkeypatch, tmp_path):
    """A GSC-scoped sync job must rebuild the seo_performance chunk too (the
    widen list), or the chunk would go stale as query data changes."""
    captured = {}

    from app.services import rag_sync_service
    from app.services.rag.embedder import DeterministicEmbedder

    def fake_build_chunks(db_, property_id=None, sources=None, **kw):
        captured["sources"] = sources
        return []

    monkeypatch.setattr(rag_sync_service, "build_chunks", fake_build_chunks)
    monkeypatch.setattr(rag_sync_service, "_provider_changed", lambda *a: False)

    p = _prop(db, "Widen Court")
    from app.models import RagSyncJob

    job = RagSyncJob(property_id=p.id, source="gsc", reason="test")
    db.add(job)
    db.commit()
    result = rag_sync_service.drain_queue(
        db=db, provider=DeterministicEmbedder(), chroma_dir=str(tmp_path / "chroma")
    )
    assert result["processed"] == 1, result
    assert "seo_performance" in (captured.get("sources") or [])
    assert "opportunity_engine" in (captured.get("sources") or [])


def test_chunk_retrievable_by_hybrid_retriever(db, tmp_path):
    """End to end with the deterministic embedder: the question the briefing
    hands to Nora retrieves the chunk that actually names the queries."""
    from app.services.rag.embedder import DeterministicEmbedder
    from app.services.rag.indexer import build_index
    from app.services.rag.retriever import retrieve

    p = _prop(db, "Retrieval Court")
    _seed_striking(db, p.id)
    chroma_dir = str(tmp_path / "chroma")
    build_index(db, DeterministicEmbedder(), chroma_dir)

    hits = retrieve(
        db, DeterministicEmbedder(),
        "Which striking-distance queries deserve content investment first?",
        property_id=p.id, chroma_dir=chroma_dir,
    )
    texts = " ".join(h.text for h in hits)
    assert "senior apartments near me" in texts
    # And the citation resolves to the seo_performance registry entry.
    assert any(h.citation.source_table == "seo_performance" for h in hits)
