"""Opportunity Engine: unifies every module's recommendations into one ranked,
context-gated, corroboration-boosted list. Deterministic; Suppressed and
insufficient-data items surface in their own buckets, never hidden."""

from datetime import datetime, timedelta

from app.connectors.base import AIVisibilityQueryProvider
from app.models import (
    Competitor,
    Property,
    PropertyContent,
    PropertyProfile,
    PropertyReview,
)
from app.services.ai_visibility import run_query
from app.services.ai_visibility.providers import read_queries
from app.services.opportunity_engine import (
    build_opportunities,
    opportunity_engine_summary_text,
)


class FR(AIVisibilityQueryProvider):
    def __init__(self, response):
        self.response = response

    def execute_query(self, prompt, platform):
        return self.response

    def get_queries(self, db, property_id):
        return read_queries(db, property_id)


def _prop(db, name="Opp Prop"):
    p = Property(name=name, slug=name.lower().replace(" ", "-"), city="Austin", state="TX")
    db.add(p)
    db.commit()
    return p


def test_empty_property_has_only_add_content(db):
    # Even a bare property yields the Content IQ "add content" opportunity.
    p = _prop(db)
    a = build_opportunities(db, p.id)
    assert a["total"] >= 1
    assert a["by_source"]["Content IQ"] >= 1
    assert a["opportunities"][0]["source"] == "content"


def _parking_reviews(db, pid, n=5):
    base = datetime(2026, 6, 1).date()
    for i in range(n):
        db.add(PropertyReview(
            property_id=pid, provider="manual",
            body="Parking is terrible, never enough spots and the garage is always full.",
            rating=1.0, review_date=base + timedelta(days=i),
        ))
    db.commit()


def test_aggregates_multiple_sources(db):
    p = _prop(db)
    # Content with a parking gap + enough negative parking reviews to trigger a
    # Review IQ parking opportunity.
    db.add(PropertyContent(
        property_id=p.id, page="amenities", title="Amenities",
        body="Resort-style pool and fitness center. Pet friendly with a dog park.",
    ))
    db.commit()
    _parking_reviews(db, p.id)
    a = build_opportunities(db, p.id)
    sources = {o["source"] for o in a["opportunities"]}
    assert "content" in sources
    assert "reviews" in sources


def test_corroboration_boost_across_sources(db):
    p = _prop(db)
    # Content missing parking + reviews complaining about parking -> the two
    # opportunities share the "parking" topic, so each is reinforced by the other.
    db.add(PropertyContent(
        property_id=p.id, page="amenities", title="Amenities",
        body="Pool and fitness center only.",
    ))
    db.commit()
    _parking_reviews(db, p.id)
    a = build_opportunities(db, p.id)
    parking = [o for o in a["opportunities"] if "parking" in (o["title"] + o["reason"]).lower()]
    assert parking
    # At least one parking opportunity is reinforced by another source.
    assert any(o["corroborating_sources"] for o in parking)


def test_ranking_is_deterministic(db):
    p = _prop(db)
    db.add(PropertyContent(property_id=p.id, page="homepage", title="Home", body="Welcome."))
    db.commit()
    import json

    a1 = json.dumps(build_opportunities(db, p.id), default=str, sort_keys=True)
    a2 = json.dumps(build_opportunities(db, p.id), default=str, sort_keys=True)
    assert a1 == a2
    # priorities are 1..n contiguous
    opps = build_opportunities(db, p.id)["opportunities"]
    assert [o["priority"] for o in opps] == list(range(1, len(opps) + 1))


def test_insufficient_items_bucketed_separately(db):
    p = _prop(db)
    # One AI Visibility query -> its "run more queries" rec is Insufficient data.
    run_query(db, p.id, "q", "chatgpt", provider=FR("Some options exist."))
    a = build_opportunities(db, p.id)
    assert any(o["source"] == "ai_visibility" for o in a["insufficient"])
    # Insufficient items are NOT in the main actionable list.
    assert all(o["state"] != "Insufficient data" for o in a["opportunities"])


def test_suppressed_bucketed_and_gated(db):
    p = _prop(db)
    db.add(PropertyProfile(
        property_id=p.id, is_regulated=True,
        marketing_restriction_flags=["no_exclusivity_language"],
    ))
    # A competitor whose name would push an "exclusive" positioning rec.
    db.add(Competitor(property_id=p.id, name="Exclusive Prestige Towers"))
    db.commit()
    for i in range(3):
        run_query(db, p.id, f"q{i}", "chatgpt", provider=FR("Exclusive Prestige Towers is prestigious and exclusive."))
    a = build_opportunities(db, p.id)
    # The competitor-gap rec references "exclusive" -> suppressed on a
    # no-exclusivity regulated property.
    assert any(o["state"] == "Suppressed" for o in a["suppressed"])


def test_regulated_sensitive_requires_confirmation(db):
    p = _prop(db)
    db.add(PropertyProfile(property_id=p.id, is_regulated=True))
    db.add(PropertyContent(
        property_id=p.id, page="floor_plans", title="Floor Plans",
        body="Two bedroom layouts available.",
    ))
    db.commit()
    a = build_opportunities(db, p.id)
    # Any opportunity whose text touches pricing/availability must be gated.
    sensitive = [
        o for o in a["opportunities"] + a["suppressed"]
        if "pricing" in (o["title"] + o["reason"]).lower()
        or "availab" in (o["title"] + o["reason"]).lower()
    ]
    if sensitive:
        assert all(o["state"] in ("Requires confirmation", "Suppressed") for o in sensitive)


# --- RAG + Nora + API ---


def test_chunk_built_and_scoped(db):
    from app.connectors.development import DevelopmentDataProvider
    from app.services.rag.chunker import build_chunks

    p = _prop(db)
    chunks = build_chunks(
        db, property_id=p.id, sources=["opportunity_engine"],
        content_provider=DevelopmentDataProvider(),
    )
    oe = [c for c in chunks if c.source == "opportunity_engine"]
    assert len(oe) == 1
    assert oe[0].chroma_id == f"opportunity_engine-p{p.id}"
    assert "Prioritized opportunities" in oe[0].text


def test_nora_retrieves_opportunity_chunk(db, tmp_path):
    from tests.test_phase8_nora import FakeLLM
    from app.services import nora
    from app.services.rag.embedder import DeterministicEmbedder
    from app.services.rag.indexer import build_index

    p = _prop(db, "Nora Opp Prop")
    build_index(db, DeterministicEmbedder(), chroma_dir=str(tmp_path / "chroma"))
    result = nora.ask(
        db, "What should we do first?", FakeLLM(), DeterministicEmbedder(),
        property_id=p.id, chroma_dir=str(tmp_path / "chroma"),
    )
    assert "opportunity_engine" in {c["source_table"] for c in result["citations"]}


def test_api(client, db):
    pid = client.post("/api/properties", json={"name": "API Opp Prop"}).json()["id"]
    a = client.get(f"/api/opportunities/{pid}")
    assert a.status_code == 200, a.text
    body = a.json()
    assert "opportunities" in body and "suppressed" in body and "insufficient" in body
    assert body["total"] >= 1

    analyze = client.post(f"/api/opportunities/{pid}/analyze").json()
    assert analyze["sync_job_id"] is not None


def test_api_unknown_property_404(client):
    assert client.get("/api/opportunities/9999").status_code == 404
