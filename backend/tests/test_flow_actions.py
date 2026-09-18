"""Action lifecycle with automatic retest."""

from datetime import datetime, timedelta

import pytest

from app.models import AIAction, AICitedPage, AIContentGap, ContentChange, Property
from app.services.observatory.actions import (
    MAX_RETESTS,
    _visibility,
    retest,
    retest_due,
    track_action,
    update_action,
)
from app.services.observatory.demo_seed import build_sample_portfolio
from app.services.observatory.listing_gaps import listing_gap_opportunities
from app.services.opportunity_engine import build_opportunities

NOW = datetime(2026, 9, 10, 12, 0)
TODAY = NOW.date()


def _seeded(db, name="Maple Ridge Flats"):
    build_sample_portfolio(db, now=NOW, weeks=4)
    return db.query(Property).filter_by(name=name).one()


def _listing(db, prop):
    g = listing_gap_opportunities(db, prop.id, days=28, today=TODAY)[0]
    a, created = track_action(db, prop.id, title=g["title"] + " (test)", source="ai_observatory",
                              source_label="AI Observatory", reason=g["reason"], citations=g["citations"])
    return a, created


def test_tracking_is_idempotent_and_recognizes_observatory_kinds(db):
    maple = _seeded(db)
    a, created = _listing(db, maple)
    assert created and a.kind == "listing_gap" and a.target["normalized_url"]
    again, created2 = _listing(db, maple)
    assert again.id == a.id and not created2
    gap = db.query(AIContentGap).filter_by(property_id=maple.id, status="open").first()
    if gap:
        c, _ = track_action(db, maple.id, title=gap.title + " (test)", source="ai_observatory",
                            citations=[{"source_ref": f"ai_observatory: gap={gap.id}, cluster={gap.cluster_id}"}])
        assert c.kind == "content_gap" and c.target["cluster_id"] == gap.cluster_id
    g, _ = track_action(db, maple.id, title="Refresh the leasing office photos", source="content")
    assert g.kind == "general"
    with pytest.raises(ValueError):
        track_action(db, maple.id, title="Topic with no key", kind="topic")


def test_transitions_are_enforced_and_general_actions_close_by_hand(db):
    maple = _seeded(db)
    a, _ = _listing(db, maple)
    with pytest.raises(ValueError):
        update_action(db, a.id, status="retested", today=TODAY)
    with pytest.raises(ValueError):
        update_action(db, a.id, status="done", today=TODAY)  # automatic retest kinds cannot be closed by hand
    update_action(db, a.id, status="in_progress", owner="Tina", today=TODAY)
    assert a.started_at is not None and a.owner == "Tina"
    with pytest.raises(ValueError):
        update_action(db, a.id, status="implemented", implemented_on=TODAY + timedelta(days=1), today=TODAY)
    update_action(db, a.id, status="implemented", implemented_on=TODAY, today=TODAY)
    assert a.status == "implemented" and a.retest_after == TODAY + timedelta(days=3)
    assert a.baseline["current"]["state"] in ("not_mentioned", "unreachable", "unchecked", "mentioned")
    g, _ = track_action(db, maple.id, title="Refresh the leasing office photos", source="content")
    update_action(db, g.id, status="implemented", today=TODAY)
    assert g.status == "done" and g.retest_after is None


def test_listing_retest_resolved_persists_and_inconclusive(db):
    maple = _seeded(db)
    a, _ = _listing(db, maple)
    update_action(db, a.id, status="implemented", implemented_on=TODAY - timedelta(days=4), today=TODAY)
    retest(db, a, today=TODAY)
    assert a.status == "retested" and a.outcome == "persists"
    assert "still does not name" in a.result["sentence"]

    update_action(db, a.id, status="in_progress", today=TODAY)
    page = db.query(AICitedPage).filter_by(normalized_url=a.target["normalized_url"]).one()
    page.body = (page.body or "") + " Featured: Maple Ridge Flats."
    db.commit()
    update_action(db, a.id, status="implemented", implemented_on=TODAY - timedelta(days=4), today=TODAY)
    retest(db, a, today=TODAY)
    assert a.outcome == "resolved"

    update_action(db, a.id, status="in_progress", today=TODAY)
    page.status, page.body, page.error = "blocked", None, "HTTP 403"
    db.commit()
    update_action(db, a.id, status="implemented", implemented_on=TODAY - timedelta(days=4), today=TODAY)
    for i in range(MAX_RETESTS - 1):
        retest(db, a, today=TODAY + timedelta(days=7 * i))
        assert a.status == "implemented" and a.outcome is None, "inconclusive retests are rescheduled"
    retest(db, a, today=TODAY + timedelta(days=30))
    assert a.status == "retested" and a.outcome == "inconclusive"


def test_topic_retest_reports_before_and_after_with_association_wording(db):
    lake = _seeded(db, "Lakemont Senior Residences")
    gap = db.query(AIContentGap).filter_by(property_id=lake.id).first()
    assert gap is not None
    a, _ = track_action(db, lake.id, title=gap.title + " (t)", source="ai_observatory",
                        citations=[{"source_ref": f"ai_observatory: gap={gap.id}, cluster={gap.cluster_id}"}])
    impl = TODAY - timedelta(days=12)
    update_action(db, a.id, status="implemented", implemented_on=impl, today=TODAY)
    retest(db, a, today=TODAY)
    before = _visibility(db, lake.id, impl - timedelta(days=30), impl, cluster_id=gap.cluster_id)
    after = _visibility(db, lake.id, impl, TODAY + timedelta(days=1), cluster_id=gap.cluster_id)
    r = a.result
    assert (r["before"]["numerator"], r["before"]["denominator"]) == (before["numerator"], before["denominator"])
    assert (r["after"]["numerator"], r["after"]["denominator"]) == (after["numerator"], after["denominator"])
    if a.outcome:
        assert a.outcome in ("improved", "no_change", "declined", "inconclusive")
        if a.outcome != "inconclusive":
            assert "association" in r["sentence"]


def test_fact_retest_finds_conflicts_that_persist(db):
    stone = _seeded(db, "Stonebrook Commons")
    a, _ = track_action(db, stone.id, title="Fix pets (t)", source="truth", kind="fact", target={"fact_key": "pets"})
    update_action(db, a.id, status="implemented", implemented_on=TODAY - timedelta(days=21), today=TODAY)
    retest(db, a, today=TODAY)
    assert a.result["after"]["statements"] >= 1
    if a.result["after"]["statements"] >= 3:
        assert a.outcome == "persists" and a.result["after"]["conflict"] >= 1


def test_implemented_with_a_page_logs_a_content_change(db):
    lake = _seeded(db, "Lakemont Senior Residences")
    a, _ = track_action(db, lake.id, title="Add a senior living FAQ", kind="topic", target={"topic_key": "senior"})
    update_action(db, a.id, status="implemented", implemented_on=TODAY - timedelta(days=2), today=TODAY,
                  page_url="https://www.lakemontsenior.example/faq", change_type="faq_update")
    cc = db.get(ContentChange, a.content_change_id)
    assert cc is not None and cc.change_title == "Add a senior living FAQ" and cc.date_implemented == TODAY - timedelta(days=2)


def test_retest_due_only_takes_elapsed_actions_and_never_fetches_sample_pages(db, monkeypatch):
    import app.services.observatory.citation_pages as cp

    monkeypatch.setattr(cp, "_store_fetch", lambda *a, **k: pytest.fail("sample page fetched"))
    maple = _seeded(db)
    a, _ = _listing(db, maple)
    update_action(db, a.id, status="implemented", implemented_on=TODAY, today=TODAY)
    assert retest_due(db, today=TODAY)["retested"] == 0
    assert retest_due(db, today=TODAY + timedelta(days=3))["retested"] >= 1
    assert db.get(AIAction, a.id).status in ("retested", "implemented")


def test_opportunities_carry_tracked_status(db):
    maple = _seeded(db)
    out = build_opportunities(db, maple.id, today=TODAY)
    opp = out["opportunities"][0]
    a, _ = track_action(db, maple.id, title=opp["title"], source=opp["source"], citations=opp.get("citations"))
    again = build_opportunities(db, maple.id, today=TODAY)
    match = next(o for o in again["opportunities"] if o["title"] == opp["title"])
    assert match["action"] == {"id": a.id, "status": "open", "outcome": None}


def test_sample_seed_drives_actions_through_the_real_lifecycle(db):
    _seeded(db)
    rows = db.query(AIAction).all()
    assert {r.status for r in rows} >= {"retested", "in_progress"}
    for r in rows:
        if r.status == "retested":
            assert r.result and r.result.get("sentence")


def test_endpoints(client, db):
    maple = _seeded(db)
    r = client.post("/api/ai-observatory/actions", json={"property_id": maple.id, "title": "Update the pet FAQ", "kind": "topic",
                                                          "target": {"topic_key": "pets"}})
    assert r.status_code == 200 and r.json()["created"] is True
    aid = r.json()["id"]
    assert client.post("/api/ai-observatory/actions", json={"property_id": maple.id, "title": "Update the pet FAQ",
                                                             "kind": "topic", "target": {"topic_key": "pets"}}).json()["created"] is False
    assert client.patch(f"/api/ai-observatory/actions/{aid}", json={"status": "in_progress"}).status_code == 200
    assert client.patch(f"/api/ai-observatory/actions/{aid}", json={"status": "retested"}).status_code == 422
    assert client.post(f"/api/ai-observatory/actions/{aid}/retest").status_code == 422
    done = client.patch(f"/api/ai-observatory/actions/{aid}", json={"status": "implemented"})
    assert done.status_code == 200 and done.json()["status"] == "implemented"
    assert client.post(f"/api/ai-observatory/actions/{aid}/retest").status_code == 200
    listing = client.get("/api/ai-observatory/actions", params={"property_id": maple.id}).json()
    assert any(x["id"] == aid for x in listing["actions"])
    assert client.patch("/api/ai-observatory/actions/999999", json={"status": "open"}).status_code == 404
    assert client.post("/api/ai-observatory/actions", json={"property_id": maple.id, "title": "x", "kind": "fact"}).status_code == 422
