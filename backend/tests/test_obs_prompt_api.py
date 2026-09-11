"""Phase 19 (2): prompt library endpoints and the jobs that wrap generation."""

from app.config import settings
from app.models import AIVisibilityPrompt, Property
from app.services.jobs.queue import enqueue
from app.services.jobs.runner import claim_next, run_one
from app.services.observatory.markets import assign_property_market


def _prop(db, name="Api Prompt Court"):
    p = Property(name=name, slug=name.lower().replace(" ", "-"), city="Aurora", state="CO")
    db.add(p)
    db.commit()
    assign_property_market(db, p)
    db.commit()
    return p


def test_generate_endpoint_builds_universe_and_clusters(client, db, monkeypatch):
    monkeypatch.setattr(settings, "demo_mode", True)  # deterministic embeddings
    monkeypatch.setattr(settings, "ai_cluster_threshold", 0.5)
    p = _prop(db)
    r = client.post(f"/api/ai-observatory/prompts/generate?property_id={p.id}")
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["brand_prompts"]["created"] >= 6
    assert body["market_prompts"]["created"] > 20
    assert body["clusters"]["market"] > 0 and body["clusters"]["brand"] > 0
    assert body["assignments"]["assignments_active"] > 0
    assert "—" not in r.text

    listed = client.get(f"/api/ai-observatory/prompts?property_id={p.id}&include_variants=false").json()
    assert all(pr["is_representative"] for pr in listed["prompts"])
    assert {pr["scope"] for pr in listed["prompts"]} == {"market", "feature", "brand"}
    market_only = client.get(f"/api/ai-observatory/prompts?market_id={p.market_id}&scope=feature").json()
    assert all(pr["scope"] == "feature" and pr["property_id"] is None for pr in market_only["prompts"])

    clusters = client.get(f"/api/ai-observatory/clusters?property_id={p.id}").json()
    assert any(c["assigned"] for c in clusters["clusters"])
    markets = client.get("/api/ai-observatory/markets").json()["markets"]
    assert any(m["slug"] == "aurora-co" and m["property_count"] == 1 for m in markets)
    detail = client.get(f"/api/ai-observatory/markets/{p.market_id}").json()
    assert detail["properties"][0]["id"] == p.id and detail["clusters"]


def test_manual_prompt_create_and_patch(client, db):
    p = _prop(db, "Manual Court")
    r = client.post("/api/ai-observatory/prompts", json={
        "prompt_text": "Does Manual Court have a rooftop lounge?", "scope": "brand",
        "property_id": p.id, "topic_key": "amenities", "importance": 5,
    })
    assert r.status_code == 201, r.text
    prompt = r.json()["prompt"]
    assert prompt["generation_method"] == "manual" and prompt["importance"] == 5
    dup = client.post("/api/ai-observatory/prompts", json={
        "prompt_text": "  does manual court have a ROOFTOP lounge?  ", "scope": "brand", "property_id": p.id,
    })
    assert dup.json()["created"] is False and dup.json()["prompt"]["id"] == prompt["id"]

    bad = client.post("/api/ai-observatory/prompts", json={"prompt_text": "x", "scope": "market"})
    assert bad.status_code == 422
    patched = client.patch(f"/api/ai-observatory/prompts/{prompt['id']}", json={"approved": False, "importance": 9})
    assert patched.json()["prompt"]["approved"] is False and patched.json()["prompt"]["importance"] == 5
    assert db.get(AIVisibilityPrompt, prompt["id"]).approved is False


def test_generation_jobs_run_through_the_runner(db, monkeypatch):
    monkeypatch.setattr(settings, "demo_mode", True)
    monkeypatch.setattr(settings, "ai_cluster_threshold", 0.5)
    p = _prop(db, "Job Prompt Court")
    enqueue(db, "generate_property_prompts", {"property_id": p.id}, idempotency_key=f"gen:{p.id}", property_id=p.id)
    job = run_one(db, claim_next(db, "w"))
    assert job.status == "completed" and job.result["brand_prompts_created"] >= 6
    enqueue(db, "cluster_prompts", {"market_id": p.market_id}, idempotency_key=f"cluster:{p.market_id}:1")
    job = run_one(db, claim_next(db, "w"))
    assert job.status == "completed" and job.result["clusters_total"] > 0
