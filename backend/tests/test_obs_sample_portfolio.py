"""The labeled Sample Portfolio: builds a fictional demo dataset through the
real pipeline so every Observatory surface can be shown populated, keeps it
isolated from real organizations (data, budget and market runs), flags it as
sample data, and removes cleanly."""

from datetime import datetime, timedelta, timezone

from app.models import (
    AIBudget,
    AIClaim,
    AIContentGap,
    AIDiscoveredEntity,
    AIPropertyObservation,
    AIRun,
    AIVisibilityQuery,
    Company,
    Market,
    Organization,
    Property,
    PropertyContent,
)
from app.services.observatory.demo_seed import (
    SAMPLE_ORG_SLUG,
    build_sample_portfolio,
    remove_sample_portfolio,
    sample_status,
)
from app.services.observatory.markets import assign_property_market
from app.services.observatory.metrics import metrics_for_window
from app.services.observatory.tenancy import default_organization_id

NOW = datetime.now(timezone.utc).replace(hour=12, minute=0, second=0, microsecond=0, tzinfo=None)
TODAY = NOW.date()


def test_sample_portfolio_populates_every_surface(db):
    out = build_sample_portfolio(db, now=NOW, weeks=6)
    assert out["properties"] == 8 and out["runs_created"] > 60
    org = db.query(Organization).filter_by(slug=SAMPLE_ORG_SLUG).one()
    assert org.settings["sample_data"] is True

    props = db.query(Property).join(Company).filter(Company.organization_id == org.id).all()
    assert all(p.attributes["sample_data"] is True for p in props)
    assert db.query(PropertyContent).filter(PropertyContent.property_id.in_([p.id for p in props])).count() > 20

    # One market answer scores several properties, and metrics have real values.
    market_run = db.query(AIRun).filter(AIRun.organization_id == org.id, AIRun.property_id.is_(None)).first()
    scored = db.query(AIPropertyObservation).filter_by(run_id=market_run.id).count()
    assert scored >= 3
    rising = next(p for p in props if p.name == "Maple Ridge Flats")
    m = metrics_for_window(db, rising.id, TODAY - timedelta(days=60), TODAY)
    assert m["ai_visibility"]["value"] is not None and m["counts"]["eligible_count"] > 10

    # The intelligence layers have something to show.
    assert db.query(AIClaim).filter(AIClaim.property_id.in_([p.id for p in props])).count() > 0
    assert db.query(AIContentGap).filter(AIContentGap.property_id.in_([p.id for p in props])).count() > 0
    assert db.query(AIDiscoveredEntity).count() > 0

    # Another sample property's site is never "owned" from this property's view.
    from app.services.observatory.metrics import source_influence

    stonebrook = next(p for p in props if p.name == "Stonebrook Commons")
    src = source_influence(db, stonebrook.id, TODAY - timedelta(days=60), TODAY)
    types = {d["domain"]: d["source_type"] for d in src["domains"]}
    assert types.get("mapleridgeflats.example") in ("property_site", "competitor")
    assert "owned" not in {t for dom, t in types.items() if dom != "stonebrookcommons.example"}

    # Sample runs are demo-provider and free, so real cost reporting is untouched.
    runs = db.query(AIRun).filter_by(organization_id=org.id).all()
    assert {r.provider for r in runs} == {"demo"}
    assert all((r.estimated_cost or 0) == 0 for r in runs)


def test_sample_portfolio_never_scores_another_organizations_property(db):
    """A market is shared geography: a real property in the same city must
    never be scored by the sample organization's market runs."""
    real = Property(name="Real Client Property", slug="real-client", city="Lakemont", state="CO")
    db.add(real)
    db.commit()
    assign_property_market(db, real)
    db.commit()
    real_org = default_organization_id(db)
    build_sample_portfolio(db, now=NOW, weeks=2)

    assert db.query(AIPropertyObservation).filter_by(property_id=real.id).count() == 0
    assert db.query(AIVisibilityQuery).filter_by(property_id=real.id).count() == 0
    budget = db.query(AIBudget).filter_by(scope_type="org", scope_id=real_org).one_or_none()
    assert budget is None or budget.spent_runs == 0


def test_sample_portfolio_rebuild_is_idempotent_and_removal_is_clean(db):
    build_sample_portfolio(db, now=NOW, weeks=2)
    first = sample_status(db)
    build_sample_portfolio(db, now=NOW, weeks=2)
    second = sample_status(db)
    assert second["properties"] == first["properties"] == 8
    assert db.query(Organization).filter_by(slug=SAMPLE_ORG_SLUG).count() == 1

    removed = remove_sample_portfolio(db)
    assert removed["removed"] and removed["properties"] == 8
    assert sample_status(db) == {"present": False, "properties": 0, "responses": 0}
    for model in (AIRun, AIVisibilityQuery, AIPropertyObservation, AIClaim, AIContentGap, AIDiscoveredEntity):
        assert db.query(model).count() == 0
    assert db.query(Property).count() == 0 and db.query(Company).count() == 0
    assert db.query(Market).filter(Market.slug.in_(["lakemont-co", "harbor-bend-tx"])).count() == 0
    assert remove_sample_portfolio(db)["removed"] is False


def test_sample_portfolio_admin_endpoints(client, db):
    assert client.get("/api/admin/sample-portfolio").json()["present"] is False
    assert client.post("/api/admin/sample-portfolio").status_code == 422  # confirm required
    body = client.post("/api/admin/sample-portfolio?confirm=true").json()
    assert body["present"] and body["properties"] == 8 and "Sample data only" in body["note"]
    assert client.get("/api/admin/ai-ops").json()["sample_portfolio"]["present"] is True
    # A real property's usage view never includes the sample organization's runs.
    real = Property(name="Real Place", slug="real-place")
    db.add(real)
    db.commit()
    usage = client.get(f"/api/ai-observatory/costs?days=90&property_id={real.id}").json()
    assert usage["total"]["runs"] == 0 and usage["budget"]["spent_runs"] == 0
    assert client.delete("/api/admin/sample-portfolio").json()["removed"] is True
    assert client.get("/api/admin/sample-portfolio").json()["present"] is False
