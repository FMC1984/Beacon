"""Areas of concern: topic gaps with an evidence-only explanation."""

from datetime import datetime

from app.models import AIPromptCluster, AIPropertyObservation, Property
from app.services.observatory.concerns import HIGH_GAP, _level, areas_of_concern, explain_concern
from app.services.observatory.demo_seed import build_sample_portfolio

NOW = datetime(2026, 9, 10, 12, 0)
TODAY = NOW.date()


def _seeded(db, name="Lakemont Senior Residences"):
    build_sample_portfolio(db, now=NOW, weeks=4)
    return db.query(Property).filter_by(name=name).one()


def test_level_rule_is_stated_and_never_guesses_below_sample():
    assert _level(False, None, None, True) == "insufficient"
    assert _level(True, 0.2, 0.2 + HIGH_GAP, True) == "high"
    assert _level(True, 0.5, 0.62, True) == "medium"
    assert _level(True, 0.5, 0.55, True) == "monitor"
    assert _level(True, 0.8, 0.5, True) == "maintain"
    assert _level(True, 0.1, None, False) == "high" and _level(True, 0.9, None, False) == "maintain"


def test_topics_reconcile_with_observations(db):
    p = _seeded(db)
    out = areas_of_concern(db, p.id, days=28, today=TODAY)
    assert out["topics"] and sum(out["summary"].values()) == len(out["topics"])
    clusters = {c.id: (c.topic_key or "general") for c in db.query(AIPromptCluster).all()}
    obs = db.query(AIPropertyObservation).filter(AIPropertyObservation.property_id == p.id, AIPropertyObservation.eligible.is_(True),
                                                 AIPropertyObservation.cluster_id.isnot(None)).all()
    for t in out["topics"]:
        mine = [o for o in obs if clusters[o.cluster_id] == t["topic_key"]]
        assert t["answers"] == len(mine)
        assert t["visibility"]["numerator"] == sum(1 for o in mine if o.mentioned)
        assert t["absent"] == t["answers"] - t["visibility"]["numerator"]
        if t["concern"] == "insufficient":
            assert t["visibility"]["value"] is None and t["gap_points"] is None
    order = [t["concern"] for t in out["topics"]]
    rank = {"high": 0, "medium": 1, "monitor": 2, "maintain": 3, "insufficient": 4}
    assert order == sorted(order, key=rank.get), "worst first"


def test_explanation_comes_only_from_evidence(db):
    p = _seeded(db)
    topics = areas_of_concern(db, p.id, days=28, today=TODAY)["topics"]
    t = next(t for t in topics if t["absent"] > 0)
    d = explain_concern(db, p.id, t["topic_key"], days=28, today=TODAY)
    assert d["absent"] == t["absent"] and d["answers"] == t["answers"]
    assert d["explanation"][0].startswith(f"You were absent from {t['absent']} of {t['answers']}")
    assert all(row["names_you"] is None for row in d["cited_pages"] if not row["read"]), "unread pages are never called silent"
    assert d["recommended_action"]["text"] and d["recommended_action"]["state"] in ("Actionable", "Requires confirmation", "Suppressed")
    assert "forecast" in d["note"] and not any("%" in s and "predict" in s.lower() for s in d["explanation"])


def test_endpoints(client, db):
    p = _seeded(db)
    r = client.get("/api/ai-observatory/concerns", params={"property_id": p.id, "days": 28, "today": TODAY.isoformat()})
    assert r.status_code == 200
    key = r.json()["topics"][0]["topic_key"]
    assert client.get(f"/api/ai-observatory/concerns/{key}", params={"property_id": p.id, "days": 28, "today": TODAY.isoformat()}).status_code == 200
    assert client.get("/api/ai-observatory/concerns/not_a_topic", params={"property_id": p.id}).status_code == 404
    assert client.get("/api/ai-observatory/concerns", params={"property_id": 999999}).status_code == 404
