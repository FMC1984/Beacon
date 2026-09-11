"""Phase 19 (1b): default organization, market resolution from city/state,
derived owned domain, and the property -> org resolution every later phase
relies on."""

from app.models import Company, Market, Organization, Property
from app.services.observatory.markets import (
    assign_property_market,
    ensure_market,
    market_members,
    market_slug,
)
from app.services.observatory.tenancy import (
    default_organization_id,
    org_property_ids,
    property_org_id,
)


def test_default_organization_is_backfilled_by_migration(db):
    org = db.query(Organization).filter_by(slug="default").one()
    assert org.id == 1 and org.is_active
    assert default_organization_id(db) == 1


def test_market_slug_is_stable_and_url_safe():
    assert market_slug("Castle Rock", "CO") == "castle-rock-co"
    assert market_slug("  Denver ", "co") == "denver-co"
    assert market_slug("St. Louis", "MO") == "st-louis-mo"


def test_ensure_market_is_idempotent(db):
    a = ensure_market(db, "Denver", "CO")
    b = ensure_market(db, "denver", "co")
    db.commit()
    assert a.id == b.id
    assert a.name == "Denver, CO" and a.state == "CO"
    assert db.query(Market).count() == 1


def test_property_api_assigns_market_and_derives_domain(client, db):
    r = client.post(
        "/api/properties",
        json={
            "name": "Ridge Court", "city": "Castle Rock", "state": "CO",
            "website_url": "https://www.ridgecourt.com/apartments",
            "attributes": {"amenities": ["pool", "dog park"], "pet_policy": {"dogs": True}},
            "zip": "80104",
        },
    )
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["domain"] == "ridgecourt.com"
    assert body["zip"] == "80104"
    assert body["attributes"]["amenities"] == ["pool", "dog park"]
    market = db.query(Market).filter_by(slug="castle-rock-co").one()
    assert body["market_id"] == market.id

    # Moving the property re-derives its market; a bare state clears it.
    r2 = client.patch(f"/api/properties/{body['id']}", json={"city": "Parker"})
    assert r2.json()["market_id"] == db.query(Market).filter_by(slug="parker-co").one().id
    r3 = client.patch(f"/api/properties/{body['id']}", json={"city": None})
    assert r3.json()["market_id"] is None


def test_property_org_resolution_falls_back_to_default(db):
    unassigned = Property(name="Solo Court", slug="solo-court")
    db.add(unassigned)
    db.commit()
    assert property_org_id(db, unassigned.id) == default_organization_id(db)

    other = Organization(name="Acme Living", slug="acme")
    db.add(other)
    db.commit()
    company = Company(name="Acme Portfolio", slug="acme-portfolio", organization_id=other.id)
    db.add(company)
    db.commit()
    owned = Property(name="Acme Court", slug="acme-court", company_id=company.id)
    db.add(owned)
    db.commit()
    assert property_org_id(db, owned.id) == other.id
    assert org_property_ids(db, other.id) == [owned.id]
    assert unassigned.id in org_property_ids(db, default_organization_id(db))
    assert owned.id not in org_property_ids(db, default_organization_id(db))


def test_market_members_and_org_scoping(db):
    other = Organization(name="Other Org", slug="other")
    db.add(other)
    db.commit()
    company = Company(name="Other Co", slug="other-co", organization_id=other.id)
    db.add(company)
    db.commit()
    a = Property(name="A Court", slug="a-court", city="Denver", state="CO")
    b = Property(name="B Court", slug="b-court", city="Denver", state="CO", company_id=company.id)
    db.add_all([a, b])
    db.commit()
    assign_property_market(db, a)
    assign_property_market(db, b)
    db.commit()
    assert a.market_id == b.market_id
    names = [p.name for p in market_members(db, a.market_id)]
    assert names == ["A Court", "B Court"]
    assert [p.name for p in market_members(db, a.market_id, organization_id=other.id)] == ["B Court"]


def test_company_api_joins_default_organization(client, db):
    r = client.post("/api/companies", json={"name": "Fresh Co"})
    assert r.status_code == 201
    company = db.query(Company).filter_by(name="Fresh Co").one()
    assert company.organization_id == default_organization_id(db)
