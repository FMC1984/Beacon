"""Phase 19: the Observatory scale rollups are a CACHE, never a second
opinion. Every test here holds the stored numbers equal to the live
computation they were built from, because a cache that can drift into its
own arithmetic is worse than no cache at all."""

from datetime import datetime, timedelta, timezone

from app.models import (
    AICompetitorStat,
    AIRun,
    AIRunCostDaily,
    AISourceDomainRollup,
    Competitor,
    Property,
)
from app.services.observatory.costs import cost_report
from app.services.observatory.demo_seed import build_sample_portfolio, remove_sample_portfolio
from app.services.observatory.metrics import source_influence
from app.services.observatory.scale_rollups import (
    competitor_stats,
    cost_summary_cached,
    rebuild_all,
    rebuild_competitor_stats,
    rebuild_run_costs,
    rebuild_source_domains,
    source_influence_cached,
)
from app.services.observatory.tenancy import default_organization_id

NOW = datetime.now(timezone.utc).replace(hour=12, minute=0, second=0, microsecond=0, tzinfo=None)
TODAY = NOW.date()


def _seeded(db):
    build_sample_portfolio(db, now=NOW, weeks=4)
    props = db.query(Property).filter(Property.name.in_(
        ["Maple Ridge Flats", "Stonebrook Commons"])).order_by(Property.name).all()
    return props[0], props[1]


def test_source_domain_rollup_matches_the_live_computation(db):
    maple, _ = _seeded(db)
    start = TODAY - timedelta(days=29)
    live = source_influence(db, maple.id, start, TODAY, limit=1000)

    assert rebuild_source_domains(db, maple.id, 30, today=TODAY) == len(live["domains"])
    cached = source_influence_cached(db, maple.id, 30, today=TODAY, limit=1000)

    assert cached["from_rollup"] is True
    assert cached["total_citations"] == live["total_citations"]
    assert [(d["domain"], d["source_type"], d["citations"], d["responses"], d["share"])
            for d in cached["domains"]] == [
        (d["domain"], d["source_type"], d["citations"], d["responses"], d["share"])
        for d in live["domains"]]

    # Rebuilding is idempotent, not additive.
    before = db.query(AISourceDomainRollup).filter_by(property_id=maple.id, period="30d").count()
    rebuild_source_domains(db, maple.id, 30, today=TODAY)
    assert db.query(AISourceDomainRollup).filter_by(property_id=maple.id, period="30d").count() == before


def test_reader_falls_back_to_live_when_no_rollup_exists(db):
    maple, _ = _seeded(db)
    start = TODAY - timedelta(days=29)
    live = source_influence(db, maple.id, start, TODAY, limit=5)
    # 30d is cached, 45d is not: the uncached window must still answer.
    uncached = source_influence_cached(db, maple.id, 45, today=TODAY, limit=5)
    assert uncached["from_rollup"] is False
    cached_window = source_influence_cached(db, maple.id, 30, today=TODAY, limit=5)
    assert cached_window["from_rollup"] is False  # not built yet either
    assert cached_window["total_citations"] == live["total_citations"]


def test_run_cost_rollup_totals_match_the_live_cost_report(db):
    _seeded(db)
    org = default_organization_id(db)
    sample_org = db.query(AIRun.organization_id).filter(AIRun.organization_id != org).first()
    org_id = sample_org[0] if sample_org else org

    live = cost_report(db, days=30, today=TODAY, organization_id=org_id)["total"]
    rebuild_run_costs(db, organization_id=org_id, today=TODAY)
    cached = cost_summary_cached(db, org_id, days=30, today=TODAY)

    assert cached["from_rollup"] is True
    assert cached["runs"] == live["runs"]
    assert cached["by_status"] == live["by_status"]
    assert cached["tokens"]["input"] == live["tokens"]["input"]
    assert cached["tokens"]["output"] == live["tokens"]["output"]
    assert cached["search_operations"] == live["search_operations"]
    # Demo runs carry a real configured rate of zero, so both paths read
    # MODELED $0.00. What matters is that the cache agrees with the live read.
    assert cached["cost"]["label"] == live["cost"]["label"]
    assert cached["cost"]["estimated_usd"] == live["cost"]["estimated_usd"]
    assert cached["cost"]["priced_runs"] == live["cost"]["priced_runs"]


def test_run_cost_rollup_carries_partial_pricing_honestly(db):
    maple, _ = _seeded(db)
    org_id = db.query(AIRun.organization_id).filter(AIRun.property_id == maple.id).first()[0]
    # A model with no configured rate: its run has no dollar figure at all,
    # which is what makes the window's total a lower bound.
    db.add(AIRun(organization_id=org_id, property_id=maple.id, platform="chatgpt", provider="openai",
                 model="gpt-5-mini", run_scope="property", status="success",
                 started_at=NOW - timedelta(days=1), estimated_cost=None, token_input=900))
    db.commit()
    rebuild_run_costs(db, organization_id=org_id, today=TODAY)
    cached = cost_summary_cached(db, org_id, days=30, today=TODAY)
    live = cost_report(db, days=30, today=TODAY, organization_id=org_id)["total"]

    assert cached["cost"]["coverage"] == live["cost"]["coverage"] == "partial"
    assert cached["cost"]["estimated_usd"] == live["cost"]["estimated_usd"]
    assert cached["cost"]["priced_runs"] == live["cost"]["priced_runs"]
    assert cached["cost"]["runs"] == cached["cost"]["priced_runs"] + 1
    assert "lower bound" in cached["cost"]["note"]


def test_competitor_standings_reconcile_with_the_observations(db):
    _, stonebrook = _seeded(db)
    rebuild_competitor_stats(db, stonebrook.id, 30, today=TODAY)
    out = competitor_stats(db, stonebrook.id, days=30, today=TODAY)

    tracked = db.query(Competitor).filter_by(property_id=stonebrook.id).count()
    assert len(out["competitors"]) == tracked and out["from_rollup"] is True
    for row in out["competitors"]:
        # Answers the competitor appeared in split cleanly into shared and won.
        assert row["co_mentions"] + row["competitor_wins"] == row["competitor_mentions"]
        assert row["competitor_mentions"] <= row["shared_responses"]
        if row["shared_responses"] >= out["minimum_sample"]:
            assert row["competitor_win_rate"] == round(row["competitor_wins"] / row["shared_responses"], 4)
        else:
            assert row["competitor_win_rate"] is None  # never a misleading zero


def test_standings_build_on_demand_and_endpoint_reports_sample(db, client):
    _, stonebrook = _seeded(db)
    assert db.query(AICompetitorStat).filter_by(property_id=stonebrook.id).count() == 0
    body = client.get(f"/api/ai-observatory/competitors/standings?property_id={stonebrook.id}&days=30").json()
    assert body["from_rollup"] is False  # built on the spot rather than shown empty
    assert body["competitors"] and "never a misleading zero" not in body["note"]
    assert db.query(AICompetitorStat).filter_by(property_id=stonebrook.id).count() > 0


def test_rebuild_all_covers_every_cached_window_and_survives_removal(db):
    _seeded(db)
    out = rebuild_all(db, today=TODAY)
    assert out["windows"] == [7, 30, 90] and out["properties"] >= 8
    assert out["cost_rows"] > 0
    periods = {p for (p,) in db.query(AISourceDomainRollup.period).distinct()}
    assert periods == {"7d", "30d", "90d"}

    # Removing the properties must not leave their numbers behind in the
    # cache: stale rows for a deleted property are exactly the kind of ghost
    # figure the Observatory is not allowed to show.
    remove_sample_portfolio(db)
    assert db.query(AISourceDomainRollup).count() == 0
    assert db.query(AICompetitorStat).count() == 0
    assert db.query(AIRunCostDaily).count() == 0
    assert rebuild_all(db, today=TODAY)["pruned"] == 0
