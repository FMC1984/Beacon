"""Platform-ready structure, Source Influence Matrix, and market / comp-set standing."""

from datetime import datetime

import pytest

from app.models import AICitation, AICitedPage, AIPropertyObservation, Competitor, Property
from app.services.ai_visibility.reference import platform_availability, platform_keys
from app.services.observatory.demo_seed import build_sample_portfolio
from app.services.observatory.metrics import _window, metrics_for_window
from app.services.observatory.platform_breakdown import platform_breakdown
from app.services.observatory.rollups import rebuild_rollups
from app.services.observatory.source_matrix import source_matrix
from app.services.observatory.standing import property_standing

NOW = datetime(2026, 9, 10, 12, 0)
TODAY = NOW.date()


def _seeded(db):
    build_sample_portfolio(db, now=NOW, weeks=4)
    rebuild_rollups(db)
    return db.query(Property).filter_by(name="Maple Ridge Flats").one()


def test_every_platform_has_an_honest_availability_state():
    assert {"chatgpt", "gemini", "claude", "perplexity", "copilot", "grok", "google_ai_overviews"} <= set(platform_keys())
    assert platform_availability("chatgpt")["state"] == "live"
    g = platform_availability("gemini")
    assert g["state"] == "needs_key" and g["env_var"] == "BEACON_GEMINI_API_KEY"
    assert platform_availability("claude")["env_var"] == "BEACON_ANTHROPIC_API_KEY"
    assert platform_availability("grok")["state"] == "planned"
    assert platform_availability("copilot")["state"] == "no_api"
    assert platform_availability("google_ai_overviews")["state"] == "no_api"


def test_unbuilt_connector_is_never_called(monkeypatch):
    from app.config import settings
    from app.services.ai_visibility.providers import PlatformNotConnectedError, get_ai_visibility_provider

    monkeypatch.setattr(settings, "demo_mode", False)
    for key in ("grok", "google_ai_overviews", "copilot"):
        with pytest.raises(PlatformNotConnectedError):
            get_ai_visibility_provider(key)


def test_platform_breakdown_lists_the_whole_roster_and_reconciles(db):
    maple = _seeded(db)
    out = platform_breakdown(db, maple.id, days=28, today=TODAY)
    assert {r["platform"] for r in out["platforms"]} == set(platform_keys())
    start, end = _window(28, TODAY)
    total = metrics_for_window(db, maple.id, start, end)["counts"]["eligible_count"]
    chat = next(r for r in out["platforms"] if r["platform"] == "chatgpt")
    assert chat["answers"] == total and chat["availability"]["state"] == "live"
    assert chat["top_sources"] and abs(sum(s["share"] for s in chat["top_sources"])) <= 1.0001
    for r in out["platforms"]:
        if r["platform"] != "chatgpt":
            assert r["answers"] == 0 and r["ai_visibility"]["value"] is None and r["availability"]["state"] != "live"
    assert out["platforms"][0]["platform"] == "chatgpt", "live platforms first"


def test_source_matrix_reconciles_and_never_calls_an_unread_source_absent(db):
    maple = _seeded(db)
    out = source_matrix(db, maple.id, days=28, today=TODAY)
    rids = {r for (r,) in db.query(AIPropertyObservation.response_id).filter_by(property_id=maple.id, eligible=True)}
    assert out["total_citations"] == db.query(AICitation).filter(AICitation.response_id.in_(rids)).count()
    own = next(s for s in out["sources"] if s["source_type"] == "owned")
    assert own["presence"] == "owned" and own["action"] in ("expand", "strengthen")
    assert all(s["accuracy"] is None for s in out["sources"]), "accuracy is not graded without the Truth layer"
    for s in out["sources"]:
        assert s["by_platform"].keys() <= {"chatgpt"}
        if s["presence"] == "absent":
            assert s["pages"]["read"] >= 1 and s["action"] in ("fix", "opportunity")
    # Make every page of one absent/present directory unreadable: it becomes unknown, not absent.
    target = next(s for s in out["sources"] if s["source_type"] == "directory" and s["pages"]["read"] >= 1)
    for page in db.query(AICitedPage).filter(AICitedPage.domain == target["domain"]).all():
        page.status, page.error, page.body = "blocked", "HTTP 403", None
    db.commit()
    again = next(s for s in source_matrix(db, maple.id, days=28, today=TODAY)["sources"] if s["domain"] == target["domain"])
    assert again["presence"] == "unknown" and again["competitor_advantage"] == "unknown" and again["action"] in ("verify", "check")


def test_competitor_advantage_needs_a_competitor_on_a_page_that_omits_you(db):
    maple = _seeded(db)
    comp = db.query(Competitor).filter_by(property_id=maple.id).first()
    page = db.query(AICitedPage).filter(AICitedPage.normalized_url == "rent.com/lakemont-co").one()
    page.body = f"Featured communities: {comp.name} and others."
    db.commit()
    row = next(s for s in source_matrix(db, maple.id, days=28, today=TODAY)["sources"] if s["domain"] == "rent.com")
    assert comp.name in row["competitors_named"]
    assert row["competitor_advantage"] == "high" and row["presence"] in ("absent", "present")


def test_standing_ranks_market_and_comp_set_separately(db):
    maple = _seeded(db)
    out = property_standing(db, maple.id, days=28, today=TODAY)
    cs = out["comp_set"]
    assert cs["available"] and cs["size"] == cs["competitors"] + 1 and 1 <= cs["rank"] <= cs["size"]
    mine = next(e for e in cs["ranked"] if e["is_property"])
    mentioned = db.query(AIPropertyObservation).filter_by(property_id=maple.id, eligible=True, mentioned=True).count()
    assert mine["mentions"] == mentioned
    assert cs["beating"] + len(cs["ahead_of_you"]) <= cs["competitors"]
    mk = out["market"]
    assert mk["available"] and 1 <= mk["rank"] <= mk["size"] <= mk["monitored"]


def test_standing_is_honest_for_a_bare_property(db):
    p = Property(name="Bare Court", slug="bare-court")
    db.add(p)
    db.commit()
    out = property_standing(db, p.id, today=TODAY)
    assert out["market"]["available"] is False and "city and state" in out["market"]["reason"]
    assert out["comp_set"]["available"] is False and "competitors" in out["comp_set"]["reason"]


def test_endpoints(client, db):
    maple = _seeded(db)
    for path in ("platforms", "sources/matrix", "standing"):
        r = client.get(f"/api/ai-observatory/{path}", params={"property_id": maple.id, "days": 28, "today": TODAY.isoformat()})
        assert r.status_code == 200, path
        assert client.get(f"/api/ai-observatory/{path}", params={"property_id": 999999}).status_code == 404
