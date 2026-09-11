"""Phase 19 (2): deterministic prompt clustering with cached embeddings,
representative selection, variant rotation, and assignments that subscribe
a property to shared market clusters only where it has a signal."""

from app.models import AIPromptAssignment, AIPromptCluster, AIPromptEmbedding, AIVisibilityPrompt, Property
from app.providers.development import DeterministicEmbeddingProvider
from app.services.observatory.assignments import properties_for_cluster, subscribe_property
from app.services.observatory.clustering import (
    cluster_prompts,
    cosine,
    embed_prompts,
    pack,
    rotate_variant,
    unpack,
)
from app.services.observatory.markets import assign_property_market
from app.services.observatory.prompt_library import generate_market_prompts, generate_property_prompts


def _prop(db, name="Cluster Court", city="Parker", state="CO", **kw):
    p = Property(name=name, slug=name.lower().replace(" ", "-"), city=city, state=state, **kw)
    db.add(p)
    db.commit()
    assign_property_market(db, p)
    db.commit()
    return p


def test_vector_packing_and_cosine():
    v = [0.5, -1.0, 2.0]
    assert unpack(pack(v)) == [0.5, -1.0, 2.0]
    assert cosine([1, 0], [1, 0]) == 1.0
    assert cosine([1, 0], [0, 1]) == 0.0
    assert cosine([0, 0], [1, 1]) == 0.0


def test_embeddings_are_cached_by_hash_and_model(db):
    p = _prop(db)
    generate_market_prompts(db, p.market_id)
    prompts = db.query(AIVisibilityPrompt).filter_by(market_id=p.market_id).all()

    class Counting(DeterministicEmbeddingProvider):
        calls = 0

        def embed(self, texts):
            Counting.calls += len(texts)
            return super().embed(texts)

    provider = Counting()
    embed_prompts(db, prompts, provider=provider)
    first = Counting.calls
    assert first == len(prompts) == db.query(AIPromptEmbedding).count()
    embed_prompts(db, prompts, provider=provider)
    assert Counting.calls == first  # nothing re-embedded


def test_clustering_groups_variants_and_is_deterministic(db):
    p = _prop(db)
    generate_market_prompts(db, p.market_id)
    provider = DeterministicEmbeddingProvider()
    report = cluster_prompts(db, market_id=p.market_id, provider=provider, threshold=0.5)
    assert report.prompts_clustered == db.query(AIVisibilityPrompt).filter_by(market_id=p.market_id).count()
    assert 0 < report.clusters_total < report.prompts_clustered  # variants collapsed
    clusters = db.query(AIPromptCluster).filter_by(market_id=p.market_id).all()
    for c in clusters:
        members = db.query(AIVisibilityPrompt).filter_by(cluster_id=c.id).all()
        assert c.variant_count == len(members)
        reps = [m for m in members if m.is_representative]
        assert len(reps) == 1 and reps[0].id == c.representative_prompt_id
        assert c.label == reps[0].prompt_text[:300]
        assert all(m.topic_key == c.topic_key and m.scope == c.scope for m in members)

    before = sorted((c.id, c.representative_prompt_id, c.variant_count) for c in clusters)
    again = cluster_prompts(db, market_id=p.market_id, provider=provider, threshold=0.5)
    assert again.clusters_created == 0
    after = sorted((c.id, c.representative_prompt_id, c.variant_count)
                   for c in db.query(AIPromptCluster).filter_by(market_id=p.market_id).all())
    assert before == after


def test_rotation_walks_representative_then_variants(db):
    p = _prop(db)
    generate_market_prompts(db, p.market_id)
    cluster_prompts(db, market_id=p.market_id, provider=DeterministicEmbeddingProvider(), threshold=0.5)
    cluster = max(db.query(AIPromptCluster).filter_by(market_id=p.market_id).all(), key=lambda c: c.variant_count)
    assert cluster.variant_count >= 2
    first = rotate_variant(db, cluster.id, 0)
    second = rotate_variant(db, cluster.id, 1)
    wrap = rotate_variant(db, cluster.id, cluster.variant_count)
    assert first.is_representative and first.id == cluster.representative_prompt_id
    assert second.id != first.id and second.cluster_id == cluster.id
    assert wrap.id == first.id


def test_assignments_subscribe_to_market_and_signaled_feature_clusters(db):
    p = _prop(db, "Assign Court", attributes={"amenities": ["dog park", "pool"]})
    generate_property_prompts(db, p.id)
    provider = DeterministicEmbeddingProvider()
    cluster_prompts(db, market_id=p.market_id, provider=provider, threshold=0.5)
    cluster_prompts(db, property_id=p.id, provider=provider, threshold=0.5)

    subs = subscribe_property(db, p.id)
    assigned = db.query(AIPromptAssignment).filter_by(property_id=p.id, active=True).all()
    clusters = {c.id: c for c in db.query(AIPromptCluster).all()}
    scopes = {clusters[a.cluster_id].scope for a in assigned}
    assert scopes == {"market", "feature", "brand"}
    feature_topics = {clusters[a.cluster_id].topic_key for a in assigned if clusters[a.cluster_id].scope == "feature"}
    # signaled (dog_park, pool) + core feature topics (pets, floor_plans);
    # rent/best_overall are core too but live in market-scope templates.
    assert {"dog_park", "pool", "pets", "floor_plans"} <= feature_topics
    assert "student" not in feature_topics and "ev_charging" not in feature_topics
    assert subs["assignments_created"] == len(assigned)

    # A market cluster resolves back to the subscribed property (Phase 3 fan-out).
    market_cluster = next(c for c in clusters.values() if c.scope == "market")
    assert properties_for_cluster(db, market_cluster.id) == [p.id]

    # Re-subscribing is idempotent; losing a signal deactivates its assignment.
    again = subscribe_property(db, p.id)
    assert again["assignments_created"] == 0
    p.attributes = {"amenities": ["pool"]}
    db.commit()
    third = subscribe_property(db, p.id)
    assert third["assignments_deactivated"] >= 1
    still = {clusters[a.cluster_id].topic_key for a in db.query(AIPromptAssignment).filter_by(property_id=p.id, active=True)}
    assert "dog_park" not in still and "pool" in still
