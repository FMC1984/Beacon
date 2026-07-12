"""Phase 15b: hybrid retrieval + deterministic reranking + debug view.
DeterministicEmbedder + temp Chroma dir; no network, no model calls."""

from datetime import date

import pytest

from app.config import settings
from app.models import Property, PropertyReview
from app.services.rag.embedder import DeterministicEmbedder
from app.services.rag.indexer import build_index
from app.services.rag.retriever import retrieve


@pytest.fixture()
def seeded(db, tmp_path):
    p = Property(name="Hybrid Heights", slug="hybrid-heights", city="Tempe")
    db.add(p)
    db.commit()
    db.add_all(
        [
            PropertyReview(
                property_id=p.id, provider="manual", rating=1,
                body="Roaches in the gym locker room, total infestation.",
                review_date=date(2026, 6, 1),
            ),
            PropertyReview(
                property_id=p.id, provider="manual", rating=2,
                body="The parking garage feels unsafe at night.",
                review_date=date(2026, 6, 2),
            ),
            PropertyReview(
                property_id=p.id, provider="manual", rating=5,
                body="Wonderful staff, quick lease renewal.",
                review_date=date(2026, 6, 3),
            ),
        ]
    )
    db.commit()
    chroma_dir = str(tmp_path / "chroma")
    build_index(db, DeterministicEmbedder(), chroma_dir)
    return p, chroma_dir


def test_keyword_overlap_ranks_matching_chunk_first(seeded, db):
    p, chroma_dir = seeded
    got = retrieve(
        db, DeterministicEmbedder(), "roaches in the gym",
        property_id=p.id, top_k=3, chroma_dir=chroma_dir,
    )
    assert got, "retrieval returned nothing"
    top = got[0]
    assert "Roaches in the gym" in top.text
    assert "roaches" in top.match_explanation["matched_keywords"]
    assert "gym" in top.match_explanation["matched_keywords"]
    assert top.score > got[-1].score


def test_explanation_carries_components_and_weights(seeded, db):
    p, chroma_dir = seeded
    got = retrieve(
        db, DeterministicEmbedder(), "parking garage safety",
        property_id=p.id, top_k=2, chroma_dir=chroma_dir,
    )
    exp = got[0].match_explanation
    assert set(exp["components"]) == {
        "semantic_similarity", "keyword_overlap", "phrase_match",
        "topic_overlap", "entity_overlap", "recency",
    }
    assert exp["weights"] == pytest.approx(exp["weights"])  # present + numeric
    assert exp["final_score"] == got[0].score
    # topic overlap fires via the shared taxonomy (query + chunk both parking)
    assert "parking" in exp["matched_topics"]


def test_topic_filter_prefilters_candidates(seeded, db):
    from app.models import RAGChunk

    p, chroma_dir = seeded
    got = retrieve(
        db, DeterministicEmbedder(), "resident complaints",
        property_id=p.id, top_k=5, chroma_dir=chroma_dir, topics=["pest"],
    )
    assert got
    rows = {r.chroma_id: r for r in db.query(RAGChunk).all()}
    # Every returned chunk is genuinely pest-tagged (the raw review AND the
    # Review Intelligence summary that reports the pest complaint both qualify).
    for c in got:
        assert "pest" in rows[c.chroma_id].enrichment["topics"]
    # The parking-only and staff-only reviews are excluded by the pre-filter.
    returned = {c.chroma_id for c in got}
    excluded = [
        cid for cid, r in rows.items()
        if r.source == "reviews" and "pest" not in (r.enrichment or {}).get("topics", [])
    ]
    assert excluded and not (set(excluded) & returned)


def test_source_filter(seeded, db):
    p, chroma_dir = seeded
    got = retrieve(
        db, DeterministicEmbedder(), "anything at all",
        property_id=p.id, top_k=10, chroma_dir=chroma_dir, source="reviews",
    )
    assert got and all(c.citation.source_table == "property_reviews" for c in got)


def test_retrieval_is_deterministic(seeded, db):
    p, chroma_dir = seeded
    a = retrieve(db, DeterministicEmbedder(), "gym pests", property_id=p.id, chroma_dir=chroma_dir)
    b = retrieve(db, DeterministicEmbedder(), "gym pests", property_id=p.id, chroma_dir=chroma_dir)
    assert [(c.chroma_id, c.score) for c in a] == [(c.chroma_id, c.score) for c in b]


def test_debug_endpoint_explains_matches(client, db, tmp_path, monkeypatch):
    monkeypatch.setattr(settings, "demo_mode", True)  # deterministic embedder
    monkeypatch.setattr(settings, "chroma_dir", str(tmp_path / "chroma"))
    p = Property(name="Debug Court", slug="debug-court")
    db.add(p)
    db.commit()
    db.add(
        PropertyReview(
            property_id=p.id, provider="manual", rating=1,
            body="Broken washer and dryer, maintenance ignored my work order.",
            review_date=date(2026, 6, 1),
        )
    )
    db.commit()
    assert client.post("/api/admin/reindex").json()["status"] == "ok"

    r = client.get(
        "/api/admin/retrieval-debug",
        params={"q": "washer and dryer maintenance", "property_id": p.id},
    )
    assert r.status_code == 200
    body = r.json()
    assert body["query"] == "washer and dryer maintenance"
    top = body["results"][0]
    assert top["final_score"] > 0
    assert "maintenance" in top["matched_keywords"]
    # phrases are stopword-filtered bigrams: "washer dryer" matches the
    # chunk's "washer and dryer"
    assert "washer dryer" in top["matched_phrases"]
    assert "maintenance" in top["matched_topics"]
    assert top["components"]["keyword_overlap"] > 0
