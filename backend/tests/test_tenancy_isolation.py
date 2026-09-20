"""Strict tenant isolation: two organizations, one property each; nothing of
one is reachable from the other, on every route that names a property."""

import pytest

from app.auth.service import create_user, set_membership
from app.models import Company, NoraConversation, Organization, Property
from app.services.observatory.demo_seed import build_sample_portfolio
from tests.test_auth_coverage import api_routes

PW = "correct horse battery"


def _tenant(db, slug: str, city: str):
    # Paid (override) so writes are judged on tenancy, not on billing.
    org = Organization(name=slug.upper(), slug=slug, is_active=True,
                       settings={"billing_override": {"active": True, "reason": "test"}})
    db.add(org)
    db.commit()
    company = Company(name=f"{slug} co", slug=f"{slug}-co", organization_id=org.id)
    db.add(company)
    db.commit()
    prop = Property(name=f"{slug} Flats", slug=f"{slug}-flats", company_id=company.id, city=city, state="CO",
                    website_url=f"https://www.{slug}.example")
    db.add(prop)
    db.commit()
    owner = create_user(db, f"{slug}@example.com", PW)
    set_membership(db, owner, org.id, "owner")
    return org, company, prop, owner


def _token(client, email):
    r = client.post("/api/auth/login", json={"email": email, "password": PW})
    assert r.status_code == 200, r.text
    return r.json()["token"]


def _h(token, org_id=None):
    h = {"Authorization": f"Bearer {token}"}
    if org_id is not None:
        h["X-Beacon-Org"] = str(org_id)
    return h


@pytest.fixture()
def two_tenants(db):
    a = _tenant(db, "alpha", "Denver")
    b = _tenant(db, "bravo", "Austin")
    return a, b


def test_lists_are_confined_to_the_acting_organization(client, db, two_tenants):
    (org_a, comp_a, prop_a, owner_a), (org_b, comp_b, prop_b, owner_b) = two_tenants
    ta = _token(client, owner_a.email)
    props = client.get("/api/properties", headers=_h(ta)).json()
    assert [p["id"] for p in props] == [prop_a.id]
    comps = client.get("/api/companies", headers=_h(ta)).json()
    assert [c["id"] for c in comps] == [comp_a.id]
    assert client.get("/api/uploads", headers=_h(ta)).json() == []
    dash = client.get("/api/dashboard", headers=_h(ta))
    assert dash.status_code == 200
    assert client.get("/api/dashboard", params={"property_id": prop_b.id}, headers=_h(ta)).status_code == 404
    assert client.get("/api/dashboard", params={"company_id": comp_b.id}, headers=_h(ta)).status_code == 404


def _substitute(path: str, prop_id: int) -> str | None:
    """Fill {property_id}; skip routes with other path params we cannot satisfy."""
    out = path.replace("{property_id}", str(prop_id))
    if "{" in out:
        return None
    return out


def test_every_property_route_hides_the_other_tenants_property(client, db, two_tenants):
    (org_a, comp_a, prop_a, owner_a), (org_b, comp_b, prop_b, owner_b) = two_tenants
    tb = _token(client, owner_b.email)
    checked = 0
    leaks = []
    for methods, path, dependant in api_routes():
        if "GET" not in methods:
            continue
        query_names = {p.name for p in dependant.query_params}
        if "{property_id}" in path:
            url = _substitute(path, prop_a.id)
            if url is None:
                continue
            r = client.get(url, headers=_h(tb))
        elif "property_id" in query_names and "{" not in path:
            r = client.get(path, params={"property_id": prop_a.id}, headers=_h(tb))
            if r.status_code == 422:
                continue  # needs other required params we cannot guess
        else:
            continue
        checked += 1
        if r.status_code not in (404, 403):
            leaks.append(f"GET {path} -> {r.status_code}")
    assert checked >= 40, f"only {checked} property routes were exercised"
    assert not leaks, "Cross-tenant reads that did not 404: " + ", ".join(leaks)


def test_own_property_routes_still_work(client, db, two_tenants):
    (org_a, comp_a, prop_a, owner_a), _ = two_tenants
    ta = _token(client, owner_a.email)
    for path in (f"/api/properties/{prop_a.id}", f"/api/properties/{prop_a.id}/setup", f"/api/competitors/{prop_a.id}",
                 f"/api/content/{prop_a.id}", f"/api/reviews/{prop_a.id}", f"/api/property-context/{prop_a.id}"):
        assert client.get(path, headers=_h(ta)).status_code == 200, path
    r = client.get("/api/ai-observatory/overview", params={"property_id": prop_a.id}, headers=_h(ta))
    assert r.status_code == 200, r.text


def test_writes_across_tenants_are_refused(client, db, two_tenants):
    (org_a, comp_a, prop_a, owner_a), (org_b, comp_b, prop_b, owner_b) = two_tenants
    tb = _token(client, owner_b.email)
    assert client.patch(f"/api/properties/{prop_a.id}", json={"city": "Nowhere"}, headers=_h(tb)).status_code == 404
    assert client.delete(f"/api/properties/{prop_a.id}", headers=_h(tb)).status_code == 404
    assert client.patch(f"/api/companies/{comp_a.id}", json={"name": "Taken"}, headers=_h(tb)).status_code == 404
    assert client.delete(f"/api/companies/{comp_a.id}", headers=_h(tb)).status_code == 404
    # Creating a property inside another tenant's company is refused too.
    r = client.post("/api/properties", json={"name": "Sneaky", "company_id": comp_a.id}, headers=_h(tb))
    assert r.status_code == 422
    assert db.get(Property, prop_a.id).city == "Denver"


def test_nora_conversations_never_cross_tenants(client, db, two_tenants):
    (org_a, comp_a, prop_a, owner_a), (org_b, comp_b, prop_b, owner_b) = two_tenants
    convo = NoraConversation(title="A's portfolio chat", property_id=None, organization_id=org_a.id)
    db.add(convo)
    db.commit()
    ta, tb = _token(client, owner_a.email), _token(client, owner_b.email)
    assert [c["id"] for c in client.get("/api/nora/conversations", headers=_h(ta)).json()] == [convo.id]
    assert client.get("/api/nora/conversations", headers=_h(tb)).json() == []
    assert client.get(f"/api/nora/conversations/{convo.id}", headers=_h(tb)).status_code == 404
    assert client.get(f"/api/nora/conversations/{convo.id}", headers=_h(ta)).status_code == 200
    assert client.post("/api/nora/ask", json={"question": "hi", "property_id": prop_a.id}, headers=_h(tb)).status_code == 404


def test_platform_admin_sees_all_or_acts_as_one(client, db, two_tenants):
    (org_a, comp_a, prop_a, owner_a), (org_b, comp_b, prop_b, owner_b) = two_tenants
    tina = create_user(db, "tina@example.com", PW, is_platform_admin=True)
    t = _token(client, tina.email)
    ids = {p["id"] for p in client.get("/api/properties", headers=_h(t)).json()}
    assert {prop_a.id, prop_b.id} <= ids
    ids_b = [p["id"] for p in client.get("/api/properties", headers=_h(t, org_b.id)).json()]
    assert ids_b == [prop_b.id]
    assert client.get(f"/api/properties/{prop_a.id}", headers=_h(t, org_b.id)).status_code == 404
    assert client.get(f"/api/properties/{prop_a.id}", headers=_h(t)).status_code == 200


def test_sample_portfolio_is_its_own_tenant(client, db, two_tenants):
    (org_a, comp_a, prop_a, owner_a), _ = two_tenants
    build_sample_portfolio(db, weeks=1)
    sample = db.query(Property).filter_by(name="Maple Ridge Flats").one()
    ta = _token(client, owner_a.email)
    assert client.get(f"/api/properties/{sample.id}", headers=_h(ta)).status_code == 404
    tina = create_user(db, "tina@example.com", PW, is_platform_admin=True)
    assert client.get(f"/api/properties/{sample.id}", headers=_h(_token(client, tina.email))).status_code == 200


def test_open_mode_is_unchanged(client, db):
    org = Organization(name="X", slug="x", is_active=True, settings={})
    db.add(org)
    db.commit()
    assert client.get("/api/properties").status_code == 200
    assert client.get("/api/ai-observatory/markets").status_code == 200
