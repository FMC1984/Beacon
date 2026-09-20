"""Role gates on real routes: viewers read, admins write, platform admins run admin."""

from app.auth.service import create_user, set_membership
from app.models import Organization

PW = "correct horse battery"


def _org(db, slug="a-co", paid=True):
    settings = {"billing_override": {"active": True, "reason": "test"}} if paid else {}
    org = Organization(name=slug.upper(), slug=slug, is_active=True, settings=settings)
    db.add(org)
    db.commit()
    db.refresh(org)
    return org


def test_unpaid_org_is_read_only_until_billing_starts(client, db):
    org = _org(db, "unpaid-co", paid=False)
    admin = create_user(db, "admin@unpaid.example", PW)
    set_membership(db, admin, org.id, "admin")
    t = _token(client, admin.email)
    assert client.get("/api/companies", headers=_h(t)).status_code == 200
    r = client.post("/api/companies", json={"name": "Frozen Holdings"}, headers=_h(t))
    assert r.status_code == 402 and r.json()["detail"]["code"] == "subscription_required"
    org.settings = {"billing_override": {"active": True, "reason": "audit customer"}}
    db.commit()
    assert client.post("/api/companies", json={"name": "Frozen Holdings"}, headers=_h(t)).status_code == 201


def _token(client, email):
    return client.post("/api/auth/login", json={"email": email, "password": PW}).json()["token"]


def _h(token):
    return {"Authorization": f"Bearer {token}"}


def test_viewer_reads_but_cannot_write(client, db):
    org = _org(db)
    viewer = create_user(db, "viewer@example.com", PW)
    set_membership(db, viewer, org.id, "viewer")
    t = _token(client, viewer.email)
    assert client.get("/api/companies", headers=_h(t)).status_code == 200
    r = client.post("/api/companies", json={"name": "Nope Holdings"}, headers=_h(t))
    assert r.status_code == 403
    assert client.get("/api/admin/status", headers=_h(t)).status_code == 403
    assert client.get("/api/properties", headers=_h(t)).status_code == 200
    assert client.post("/api/briefing/generate", json={"property_id": 1}, headers=_h(t)).status_code == 403


def test_admin_writes_but_not_admin_panel(client, db):
    org = _org(db)
    admin = create_user(db, "admin@example.com", PW)
    set_membership(db, admin, org.id, "admin")
    t = _token(client, admin.email)
    r = client.post("/api/companies", json={"name": "Written By Admin"}, headers=_h(t))
    assert r.status_code == 201, r.text
    assert client.get("/api/admin/status", headers=_h(t)).status_code == 403


def test_platform_admin_reaches_admin_panel(client, db):
    tina = create_user(db, "tina@example.com", PW, is_platform_admin=True)
    t = _token(client, tina.email)
    assert client.get("/api/admin/status", headers=_h(t)).status_code == 200


def test_orphan_user_sees_only_their_own_account(client, db):
    orphan = create_user(db, "orphan@example.com", PW)
    t = _token(client, orphan.email)
    assert client.get("/api/auth/me", headers=_h(t)).status_code == 200
    assert client.get("/api/companies", headers=_h(t)).status_code == 403


def test_shared_briefing_link_stays_public(client, db):
    create_user(db, "someone@example.com", PW)
    r = client.get("/api/briefing/shared/not-a-real-token")
    assert r.status_code in (404, 410)


def test_open_mode_reads_and_writes_like_before(client):
    assert client.post("/api/companies", json={"name": "Open Mode Co"}).status_code == 201
