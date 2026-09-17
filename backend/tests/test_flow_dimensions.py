"""Regions and personas as prompt dimensions (flow P3)."""

from datetime import date

from app.models import AIClusterVisibilityDaily, AIPromptAssignment, AIPromptCluster, AIVisibilityPrompt, Property, Submarket
from app.models.property_profile import PropertyProfile
from app.providers.development import DeterministicEmbeddingProvider
from app.services.observatory.assignments import subscribe_property
from app.services.observatory.clustering import cluster_prompts
from app.services.observatory.dimensions import visibility_dimensions
from app.services.observatory.markets import assign_property_market
from app.services.observatory.prompt_library import generate_property_prompts

TODAY = date(2026, 9, 10)


def _prop(db, name, **kw):
    p = Property(name=name, slug=name.lower().replace(" ", "-"), city="Castle Rock", state="CO", **kw)
    db.add(p)
    db.commit()
    assign_property_market(db, p)
    db.commit()
    return p


def _assigned_clusters(db, pid):
    return (
        db.query(AIPromptCluster).join(AIPromptAssignment, AIPromptAssignment.cluster_id == AIPromptCluster.id)
        .filter(AIPromptAssignment.property_id == pid, AIPromptAssignment.active.is_(True)).all()
    )


def test_neighborhood_makes_a_submarket_and_region_prompts_only_its_property_subscribes_to(db):
    old_town = _prop(db, "Old Town Lofts", attributes={"neighborhood": "Old Town"})
    elsewhere = _prop(db, "Meadow Flats")
    generate_property_prompts(db, old_town.id)
    generate_property_prompts(db, elsewhere.id)
    sm = db.query(Submarket).filter_by(slug="old-town").one()
    assert old_town.submarket_id == sm.id and elsewhere.submarket_id is None
    region = db.query(AIVisibilityPrompt).filter(AIVisibilityPrompt.submarket_id == sm.id).all()
    assert region and all("Old Town" in r.prompt_text and r.scope == "market" for r in region)

    cluster_prompts(db, market_id=old_town.market_id, provider=DeterministicEmbeddingProvider(), threshold=0.5)
    assert db.query(AIPromptCluster).filter_by(geography="old-town").count() >= 1
    subscribe_property(db, old_town.id)
    subscribe_property(db, elsewhere.id)
    assert any(c.geography == "old-town" for c in _assigned_clusters(db, old_town.id))
    assert not any(c.geography for c in _assigned_clusters(db, elsewhere.id))


def test_persona_prompts_subscribe_by_audience_never_by_guess(db):
    senior = _prop(db, "Golden Years")
    db.add(PropertyProfile(property_id=senior.id, property_type="senior"))
    plain = _prop(db, "Plain Court")
    db.commit()
    out = generate_property_prompts(db, senior.id)
    assert out["personas"] == ["retiree"]
    cluster_prompts(db, market_id=senior.market_id, provider=DeterministicEmbeddingProvider(), threshold=0.5)
    assert db.query(AIPromptCluster).filter_by(persona="retiree").count() >= 1
    subscribe_property(db, senior.id)
    subscribe_property(db, plain.id)
    assert any(c.persona == "retiree" for c in _assigned_clusters(db, senior.id))
    assert not any(c.persona == "retiree" for c in _assigned_clusters(db, plain.id))


def test_dimensions_group_rollups_and_gate_the_sample(db):
    p = _prop(db, "Dim Court", attributes={"neighborhood": "Old Town"})
    generate_property_prompts(db, p.id)
    sm = db.query(Submarket).filter_by(slug="old-town").one()
    geo = AIPromptCluster(market_id=p.market_id, scope="market", label="Old Town apts", topic_key="neighborhoods",
                          geography="old-town", importance=4)
    fam = AIPromptCluster(market_id=p.market_id, scope="feature", label="family", topic_key="schools",
                          persona="family", importance=3)
    db.add_all([geo, fam])
    db.flush()
    db.add(AIClusterVisibilityDaily(day=TODAY, property_id=p.id, cluster_id=geo.id, eligible_count=5, mentioned_count=4,
                                    rollup_key=f"{p.id}:{geo.id}:{TODAY}"))
    db.add(AIClusterVisibilityDaily(day=TODAY, property_id=p.id, cluster_id=fam.id, eligible_count=2, mentioned_count=2,
                                    rollup_key=f"{p.id}:{fam.id}:{TODAY}"))
    db.commit()
    out = visibility_dimensions(db, p.id, days=7, today=TODAY)
    assert out["property_geography"] == sm.slug
    region = out["regions"][0]
    assert region["label"] == "Old Town" and region["ai_visibility"]["value"] == 0.8 and region["answers"] == 5
    persona = out["personas"][0]
    assert persona["label"] == "Family with children" and persona["ai_visibility"]["value"] is None, "2 answers is below the gate"


def test_patch_merges_attributes_and_derives_the_submarket(client, db):
    p = client.post("/api/properties", json={"name": "Merge Court", "city": "Castle Rock", "state": "CO",
                                             "attributes": {"amenities": ["Pool"]}}).json()
    r = client.patch(f"/api/properties/{p['id']}", json={"attributes": {"neighborhood": "Old Town"}}).json()
    assert r["attributes"] == {"amenities": ["Pool"], "neighborhood": "Old Town"}
    assert r["submarket_id"] is not None
    r = client.patch(f"/api/properties/{p['id']}", json={"attributes": {"neighborhood": None}}).json()
    assert r["attributes"] == {"amenities": ["Pool"]} and r["submarket_id"] is None
    assert client.get("/api/ai-observatory/dimensions", params={"property_id": p["id"]}).status_code == 200
    assert client.get("/api/ai-observatory/dimensions", params={"property_id": 999999}).status_code == 404
