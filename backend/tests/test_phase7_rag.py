"""Phase 7: chunking, indexing, retrieval, citations. Runs entirely locally:
DeterministicEmbedder + temp Chroma dir, no network, no API key."""

import pytest

from app.constants import AI_TRAFFIC_DISCLOSURE
from app.models import RAGChunk
from app.services.rag.chunker import build_chunks
from app.services.rag.embedder import (
    DeterministicEmbedder,
    MissingAPIKeyError,
    get_embedder,
)
from app.services.rag.indexer import build_index
from app.services.rag.retriever import retrieve
from tests.test_phase2_uploads import make_property, post_upload
from tests.test_phase4_gbp_paid import post_paid
from tests.test_phase5_crm import post_crm


@pytest.fixture()
def seeded(client, db):
    prop_a = make_property(client, "Solara Flats")
    post_upload(client, "ga4", prop_a["id"], "ga4_traffic_with_date.csv")
    post_upload(client, "gsc", prop_a["id"], "gsc_dates.csv")
    post_upload(client, "gbp", prop_a["id"], "gbp_performance.csv")
    post_paid(client, prop_a["id"], "google_ads_campaigns.csv", "google_ads")
    post_crm(client, prop_a["id"], "crm_yardi_placeholder.csv")
    prop_b = make_property(client, "Cedar Point")
    post_upload(client, "ga4", prop_b["id"], "ga4_no_ai_recent.csv")
    return prop_a, prop_b


# --- chunker ---


def test_chunks_are_per_property_month_source(seeded, db):
    chunks = build_chunks(db)
    ids = {c.chroma_id for c in chunks}
    # Solara: 5 sources in June 2026; Cedar: GA4 in July 2026.
    assert ids == {
        "ga4_sessions_daily-p1-2026-06",
        "gsc_performance_daily-p1-2026-06",
        "gbp_metrics_daily-p1-2026-06",
        "paid_media_daily-p1-2026-06",
        "crm_leads-p1-2026-06",
        "ga4_sessions_daily-p2-2026-07",
    }


def test_ga4_chunk_text_contains_real_numbers_and_disclosure(seeded, db):
    chunk = next(
        c for c in build_chunks(db) if c.chroma_id == "ga4_sessions_daily-p1-2026-06"
    )
    assert "Solara Flats" in chunk.text
    assert "Total sessions: 1411" in chunk.text
    assert "AI referral sessions: 12" in chunk.text
    assert "ChatGPT 8 sessions" in chunk.text
    assert AI_TRAFFIC_DISCLOSURE in chunk.text
    assert "—" not in chunk.text  # no em dashes anywhere in generated text


def test_crm_chunk_reports_funnel(seeded, db):
    chunk = next(c for c in build_chunks(db) if c.source_table == "crm_leads")
    assert "1 lease" in chunk.text
    assert "Leads: 3" in chunk.text


# --- indexer ---


def test_index_builds_and_is_incremental(seeded, db, tmp_path):
    embedder = DeterministicEmbedder()
    chroma_dir = str(tmp_path / "chroma")

    # Solara: 5 source chunks + AI Query Signals + Opportunity Engine = 7.
    # Cedar: GA4 chunk + Opportunity Engine (no AI, so no AI Query Signals) = 2.
    first = build_index(db, embedder, chroma_dir)
    assert first["chunks_total"] == 9
    assert first["embedded"] == 9
    assert db.query(RAGChunk).count() == 9

    second = build_index(db, embedder, chroma_dir)
    assert second["embedded"] == 0
    assert second["unchanged"] == 9
    assert second["removed"] == 0


def test_index_updates_changed_and_removes_stale(seeded, client, db, tmp_path):
    embedder = DeterministicEmbedder()
    chroma_dir = str(tmp_path / "chroma")
    build_index(db, embedder, chroma_dir)

    # New upload changes Solara's June GA4 chunk (replace + extend to Jun 4),
    # which also changes the derived AI Query Signals chunk = 2 re-embedded.
    # The Opportunity Engine chunk text is unchanged (its opportunities did not
    # shift), so it stays among the unchanged 7.
    post_upload(client, "ga4", 1, "ga4_multi_ai.csv")
    summary = build_index(db, embedder, chroma_dir)
    assert summary["embedded"] == 2
    assert summary["unchanged"] == 7

    row = db.query(RAGChunk).filter_by(chroma_id="ga4_sessions_daily-p1-2026-06").one()
    assert row.period_end.isoformat() == "2026-06-04"


# --- retriever + citations ---


def test_retrieve_joins_citations_from_registry(seeded, db, tmp_path):
    embedder = DeterministicEmbedder()
    chroma_dir = str(tmp_path / "chroma")
    build_index(db, embedder, chroma_dir)

    results = retrieve(
        db, embedder, "AI referral sessions ChatGPT traffic", chroma_dir=chroma_dir
    )
    assert results
    top = results[0]
    assert top.citation.source_table
    assert top.citation.property_name in {"Solara Flats", "Cedar Point"}
    assert "2026-" in top.citation.date_range
    assert "property=" in top.citation.source_ref


def test_retrieve_property_filter(seeded, db, tmp_path):
    embedder = DeterministicEmbedder()
    chroma_dir = str(tmp_path / "chroma")
    build_index(db, embedder, chroma_dir)

    results = retrieve(
        db, embedder, "sessions traffic", property_id=2, chroma_dir=chroma_dir
    )
    assert results
    assert all(r.citation.property_id == 2 for r in results)


def test_retrieve_empty_index_returns_nothing(db, tmp_path):
    results = retrieve(
        db,
        DeterministicEmbedder(),
        "anything",
        chroma_dir=str(tmp_path / "chroma-empty"),
    )
    assert results == []


# --- keyless behavior ---


def test_missing_api_key_raises_clear_error(monkeypatch):
    from app.config import settings

    monkeypatch.setattr(settings, "openai_api_key", "")
    with pytest.raises(MissingAPIKeyError, match="BEACON_OPENAI_API_KEY"):
        get_embedder()
