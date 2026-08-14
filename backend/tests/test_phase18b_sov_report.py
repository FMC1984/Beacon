"""Phase 18B: AI Share of Voice report endpoints, AI Topic CRUD, CSV export,
and drilldown reconciliation - the KPI number must equal the by-topic sum
must equal the by-prompt sum must equal the underlying Mention row count."""

from datetime import datetime, timezone

import pytest

from app.connectors.base import AIVisibilityQueryProvider
from app.models import AITopic, Competitor, Mention, Property
from app.services.ai_visibility import run_query


class FR(AIVisibilityQueryProvider):
    def __init__(self, response):
        self.response = response

    def execute_query(self, prompt, platform):
        return self.response

    def get_queries(self, db, property_id):
        return []


NOW = datetime(2026, 8, 10, 12, 0, tzinfo=timezone.utc)


def _prop(db, name="Reconcile Court"):
    p = Property(name=name, slug=name.lower().replace(" ", "-"))
    db.add(p)
    db.commit()
    return p


def _run(db, prop, text, prompt_text="How is the property?", now=None):
    return run_query(
        db, prop.id, prompt_text, "chatgpt", provider=FR(text), now=now or NOW
    )


def _setup_scenario(db):
    p = _prop(db)
    comp = Competitor(property_id=p.id, name="Rival Co")
    db.add(comp)
    db.commit()
    topic = AITopic(property_id=p.id, topic_name="Pricing", priority="high")
    db.add(topic)
    db.commit()

    from app.models import AIVisibilityPrompt

    prompt = AIVisibilityPrompt(
        property_id=p.id, prompt_text="What is the price?", platform="chatgpt",
        topic_id=topic.id,
    )
    db.add(prompt)
    db.commit()

    _run(db, p, "Reconcile Court pricing is fair.", prompt_text="What is the price?")
    _run(db, p, "Reconcile Court pricing is fair again.", prompt_text="What is the price?")
    _run(db, p, "Rival Co pricing is competitive.", prompt_text="What is the price?")
    return p, comp, topic, prompt


# --- endpoints -----------------------------------------------------------------


def test_report_scope_required_without_property(client):
    r = client.get("/api/reports/share-of-voice")
    assert r.status_code == 200
    assert r.json()["scope_required"] is True


def test_report_no_competitors_message(client, db):
    p = _prop(db)
    r = client.get(f"/api/reports/share-of-voice?property_id={p.id}")
    assert r.status_code == 200
    body = r.json()
    assert body["has_competitors"] is False
    assert "competitors" in body["message"].lower()


def test_report_property_not_found(client):
    r = client.get("/api/reports/share-of-voice?property_id=999999")
    assert r.status_code == 404


def test_full_report_endpoint_shape(client, db):
    p, comp, topic, prompt = _setup_scenario(db)
    r = client.get(f"/api/reports/share-of-voice?property_id={p.id}&days=30")
    assert r.status_code == 200
    body = r.json()
    assert body["has_competitors"] is True
    assert "overview" in body and "trend" in body
    assert "by_platform" in body and "by_topic" in body
    assert body["by_topic"][0]["topic_name"] == "Pricing"
    assert "ai_share_of_voice" in body["tooltips"]


def test_kpi_endpoint(client, db):
    p, *_ = _setup_scenario(db)
    r = client.get(f"/api/reports/share-of-voice/kpi?property_id={p.id}&days=30")
    assert r.status_code == 200
    body = r.json()
    assert body["has_competitors"] is True
    assert body["share_of_voice"] == pytest.approx(2 / 3, rel=1e-3)
    assert body["rank_label"] == "#1 of 2"


def test_ranking_endpoint(client, db):
    p, comp, *_ = _setup_scenario(db)
    r = client.get(f"/api/reports/share-of-voice/ranking?property_id={p.id}&days=30")
    assert r.status_code == 200
    body = r.json()
    names = {e["name"] for e in body["ranking"]["entities"]}
    assert names == {"Reconcile Court", "Rival Co"}
    assert "winners_losers" in body


def test_topic_drilldown_endpoint(client, db):
    p, comp, topic, prompt = _setup_scenario(db)
    r = client.get(
        f"/api/reports/share-of-voice/topics/{topic.id}?property_id={p.id}&days=30"
    )
    assert r.status_code == 200
    body = r.json()
    assert body["topic"]["topic_name"] == "Pricing"
    assert len(body["prompts"]) == 1
    assert body["prompts"][0]["prompt_id"] == prompt.id


def test_topic_drilldown_wrong_property_404s(client, db):
    p, comp, topic, prompt = _setup_scenario(db)
    other = _prop(db, "Other Court")
    r = client.get(
        f"/api/reports/share-of-voice/topics/{topic.id}?property_id={other.id}&days=30"
    )
    assert r.status_code == 404


def test_prompt_drilldown_endpoint(client, db):
    p, comp, topic, prompt = _setup_scenario(db)
    r = client.get(
        f"/api/reports/share-of-voice/prompts/{prompt.id}?property_id={p.id}&days=30"
    )
    assert r.status_code == 200
    body = r.json()
    assert body["prompt"]["id"] == prompt.id
    assert len(body["responses"]) == 3


def test_response_evidence_endpoint(client, db):
    p, comp, topic, prompt = _setup_scenario(db)
    q = db.query(Mention).filter_by(entity_type="property").first()
    response_id = q.response_id
    r = client.get(
        f"/api/reports/share-of-voice/evidence?property_id={p.id}&response_id={response_id}"
    )
    assert r.status_code == 200
    body = r.json()
    assert body["response_id"] == response_id
    assert any(m["entity_type"] == "property" for m in body["mentions"])


# --- AI Topic CRUD ---------------------------------------------------------------


def test_topic_crud(client, db):
    p = _prop(db)
    r = client.post(
        f"/api/ai-visibility/{p.id}/topics",
        json={"topic_name": "Amenities", "priority": "medium"},
    )
    assert r.status_code == 201
    topic_id = r.json()["id"]

    listed = client.get(f"/api/ai-visibility/{p.id}/topics").json()["topics"]
    assert any(t["id"] == topic_id for t in listed)

    dupe = client.post(
        f"/api/ai-visibility/{p.id}/topics",
        json={"topic_name": "Amenities"},
    )
    assert dupe.status_code == 409

    deleted = client.delete(f"/api/ai-visibility/{p.id}/topics/{topic_id}")
    assert deleted.status_code == 200
    listed_after = client.get(f"/api/ai-visibility/{p.id}/topics").json()["topics"]
    assert not any(t["id"] == topic_id for t in listed_after)


def test_prompt_accepts_new_filter_fields(client, db):
    p = _prop(db)
    r = client.post(
        f"/api/ai-visibility/{p.id}/prompts",
        json={
            "prompt_text": "Is parking included?", "platform": "chatgpt",
            "audience": "renters", "persona": "young_professional",
            "location_market": "Denver", "priority": "medium", "tags": ["parking"],
        },
    )
    assert r.status_code == 201
    body = r.json()
    assert body["audience"] == "renters"
    assert body["tags"] == ["parking"]


# --- CSV export -----------------------------------------------------------------


def test_csv_export_no_metadata_leak_or_em_dash(client, db):
    p, *_ = _setup_scenario(db)
    r = client.get(f"/api/reports/share-of-voice/export.csv?property_id={p.id}&days=30")
    assert r.status_code == 200
    text = r.text.lower()
    for forbidden in ["chunk_id", "vector", "similarity", "embedding", "latency"]:
        assert forbidden not in text
    assert "—" not in r.text
    assert "AI Share of Voice" in r.text


def test_csv_export_no_competitors_still_200(client, db):
    p = _prop(db)
    r = client.get(f"/api/reports/share-of-voice/export.csv?property_id={p.id}&days=30")
    assert r.status_code == 200
    assert "competitors" in r.text.lower()


# --- drilldown reconciliation (the single highest-value test) ------------------


def test_kpi_reconciles_with_underlying_mention_rows(client, db):
    """The KPI's property_mentions figure must equal the number of Mention
    rows Beacon actually stored for this property in the window - every
    summary metric must trace back to its evidence, exactly."""
    p, comp, topic, prompt = _setup_scenario(db)

    kpi = client.get(f"/api/reports/share-of-voice/kpi?property_id={p.id}&days=30").json()
    report = client.get(f"/api/reports/share-of-voice?property_id={p.id}&days=30").json()

    raw_property_mentions = (
        db.query(Mention)
        .filter_by(entity_type="property", entity_id=p.id)
        .count()
    )
    raw_competitor_mentions = (
        db.query(Mention)
        .filter_by(entity_type="competitor", entity_id=comp.id)
        .count()
    )

    assert report["overview"]["property_mentions"] == raw_property_mentions == 2
    assert report["overview"]["competitor_mentions"] == raw_competitor_mentions == 1
    assert kpi["share_of_voice"] == report["overview"]["share_of_voice"]

    # The by-topic row for the only topic must equal the overall figure here,
    # since every eligible response in this scenario belongs to that topic.
    topic_row = next(t for t in report["by_topic"] if t["topic_id"] == topic.id)
    assert topic_row["share_of_voice"] == report["overview"]["share_of_voice"]

    # Drilling into the topic's one prompt must show exactly the mentioned
    # responses that produced the property-mention count above.
    drilldown = client.get(
        f"/api/reports/share-of-voice/prompts/{prompt.id}?property_id={p.id}&days=30"
    ).json()
    mentioned_count = sum(1 for resp in drilldown["responses"] if resp["mentioned"])
    assert mentioned_count == raw_property_mentions

    # And each mentioned response's evidence must itself carry a property
    # Mention row - the leaf of the traceability chain.
    for resp in drilldown["responses"]:
        if not resp["mentioned"]:
            continue
        evidence = client.get(
            f"/api/reports/share-of-voice/evidence"
            f"?property_id={p.id}&response_id={resp['response_id']}"
        ).json()
        assert any(m["entity_type"] == "property" for m in evidence["mentions"])
