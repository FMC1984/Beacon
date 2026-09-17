"""Listing gaps as Opportunity Engine actions (flow P1)."""

from datetime import datetime

from app.models import AICitedPage, Property
from app.services.observatory.demo_seed import build_sample_portfolio
from app.services.observatory.listing_gaps import MIN_CITATIONS, listing_gap_opportunities
from app.services.opportunity_engine import build_opportunities

NOW = datetime(2026, 9, 10, 12, 0)
TODAY = NOW.date()


def _seeded(db):
    build_sample_portfolio(db, now=NOW, weeks=4)
    return db.query(Property).filter_by(name="Maple Ridge Flats").one()


def test_only_fetched_silent_directory_pages_become_actions(db):
    maple = _seeded(db)
    actions = listing_gap_opportunities(db, maple.id, days=28, today=TODAY)
    assert actions, "the sample stocks directory pages that omit the property"
    for a in actions:
        assert "does not mention" in a["title"] and a["state"] == "Actionable"
        assert a["evidence_level"] == "MEASURED" and a["citations"][0]["page"]
        assert "no mention of" in a["citations"][0]["evidence"][1]
    # Flip every silent page to unreachable: no evidence, no action.
    for row in db.query(AICitedPage).filter(AICitedPage.status == "ok").all():
        row.status, row.error, row.body = "unreachable", "timed out", None
    db.commit()
    assert listing_gap_opportunities(db, maple.id, days=28, today=TODAY) == []


def test_low_citation_pages_are_not_tasks(db):
    maple = _seeded(db)
    actions = listing_gap_opportunities(db, maple.id, days=28, today=TODAY)
    for a in actions:
        n = int(a["citations"][0]["evidence"][0].split()[1])
        assert n >= MIN_CITATIONS


def test_listing_gaps_flow_into_the_opportunity_engine(db):
    maple = _seeded(db)
    out = build_opportunities(db, maple.id, today=TODAY)
    mine = [o for o in out["opportunities"] if "does not mention" in o["title"]]
    assert mine and all(o["source"] == "ai_observatory" and o["source_label"] == "AI Observatory" for o in mine)
    assert out["by_source"]["AI Observatory"] >= len(mine)
