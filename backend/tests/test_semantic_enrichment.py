"""Phase 15a: shared Semantic Intelligence layer. Deterministic enrichment
(topics, entities, intents, per-topic sentiment, normalization), the negation
rules, and index-time metadata stamping. No network, no model calls."""

import pytest

from app.models import Competitor, Property, PropertyReview, RAGChunk
from app.services.rag.embedder import DeterministicEmbedder
from app.services.rag.indexer import build_index
from app.services.rag.store import get_collection
from app.services.semantic import (
    enrich_text,
    match_with_negation,
    property_entity_names,
)


# --- negation rules ---


def test_negated_positive_flips():
    r = match_with_negation("The apartment is not very clean.", ["very clean"], positive=True)
    assert r.flipped == ["very clean"] and not r.clean
    assert any("flip" in rule for rule in r.rules)


def test_absence_phrase_excludes():
    r = match_with_negation("I did not have a maintenance issue.", ["maintenance"])
    assert r.excluded == ["maintenance"] and not r.clean


def test_problem_span_excludes_but_bare_no_does_not():
    assert match_with_negation("No maintenance issues at all.", ["maintenance"]).excluded == ["maintenance"]
    # "no parking" is a complaint, not an absence of the parking topic.
    assert match_with_negation("There is no parking here.", ["parking"]).clean == ["parking"]


def test_plain_cue_never_cancels_negative_terms():
    r = match_with_negation("Maintenance never fixed my broken heater.", ["broken"])
    assert r.clean == ["broken"]


def test_cue_inside_matched_term_does_not_negate():
    r = match_with_negation("Still not fixed after weeks.", ["not fixed"])
    assert r.clean == ["not fixed"]


def test_not_only_exception_and_clause_breaker():
    assert match_with_negation("It is not only clean but spacious.", ["clean"], positive=True).clean == ["clean"]
    # breaker between cue and term ends the cue's scope
    assert match_with_negation("Not clean but great location.", ["great"], positive=True).clean == ["great"]


def test_negation_does_not_cross_sentences():
    r = match_with_negation("It is not perfect. Very clean though.", ["very clean"], positive=True)
    assert r.clean == ["very clean"]


# --- enrichment ---


def test_topics_entities_intents_normalization():
    e = enrich_text(
        "The pool is amazing but maintenance never fixed my broken AC. "
        "How do I schedule a tour?"
    )
    assert "amenities" in e["topics"]
    assert "maintenance" in e["topics"]
    assert "information_request" in e["intents"]
    assert "leasing_intent" in e["intents"]
    assert "air_conditioning" in e["normalized_terms"]
    assert {"type": "amenity", "value": "pool"} in e["entities"]
    # every assertion is explained by a matched rule, no confidence numbers
    assert e["matched_rules"]
    assert "confidence" not in e


def test_excluded_topic_reported_separately():
    e = enrich_text("I did not have a maintenance issue.")
    assert "maintenance" not in e["topics"]
    assert "maintenance" in e["topics_excluded"]


def test_per_topic_sentiment_is_clause_scoped():
    e = enrich_text("The pool is amazing but the gym was dirty.")
    assert e["sentiment_by_topic"]["amenities"] == "mixed"


def test_enrichment_is_deterministic():
    text = "Roaches everywhere, the gym is great, and rent went up."
    assert enrich_text(text) == enrich_text(text)


def test_property_entity_names_from_db_only(db):
    p = Property(name="Solara Flats", slug="solara-flats", city="Tempe")
    db.add(p)
    db.commit()
    db.add(Competitor(property_id=p.id, name="The Marlowe", aliases=["Marlowe Apts"]))
    db.commit()
    names = property_entity_names(db, p.id)
    assert names["property_name"] == ["Solara Flats"]
    assert names["city"] == ["Tempe"]
    assert set(names["competitor"]) == {"The Marlowe", "Marlowe Apts"}
    e = enrich_text("Compared to The Marlowe, Solara Flats is quieter.", extra_entities=names)
    values = {(x["type"], x["value"]) for x in e["entities"]}
    assert ("competitor", "The Marlowe") in values
    assert ("property_name", "Solara Flats") in values


# --- index-time stamping ---


@pytest.fixture()
def indexed(db, tmp_path):
    from datetime import date

    p = Property(name="Enrich Manor", slug="enrich-manor", city="Tempe")
    db.add(p)
    db.commit()
    db.add(
        PropertyReview(
            property_id=p.id,
            provider="manual",
            rating=2,
            body="Roaches in the gym and the parking garage is unsafe.",
            review_date=date(2026, 6, 1),
        )
    )
    db.commit()
    chroma_dir = str(tmp_path / "chroma")
    build_index(db, DeterministicEmbedder(), chroma_dir)
    return p, chroma_dir


def test_indexer_stamps_registry_and_chroma_metadata(indexed, db):
    p, chroma_dir = indexed
    row = (
        db.query(RAGChunk)
        .filter(RAGChunk.property_id == p.id, RAGChunk.source == "reviews")
        .first()
    )
    assert row is not None and row.enrichment is not None
    assert "pest" in row.enrichment["topics"]
    assert "parking" in row.enrichment["topics"]
    assert row.enrichment["matched_rules"]

    collection = get_collection(chroma_dir, DeterministicEmbedder().key)
    got = collection.get(ids=[row.chroma_id], include=["metadatas"])
    meta = got["metadatas"][0]
    assert meta["topic_pest"] is True
    assert meta["topic_parking"] is True
    # topic booleans are filterable
    filtered = collection.get(where={"topic_pest": True})
    assert row.chroma_id in filtered["ids"]


def test_reindex_with_unchanged_text_is_stable(indexed, db):
    p, chroma_dir = indexed
    summary = build_index(db, DeterministicEmbedder(), chroma_dir)
    assert summary["embedded"] == 0  # nothing re-embedded
    row = (
        db.query(RAGChunk)
        .filter(RAGChunk.property_id == p.id, RAGChunk.source == "reviews")
        .first()
    )
    assert row.enrichment is not None  # enrichment persisted, still present
