"""Login, sessions, invites, resets, team roles, act-as and the three ways in."""

from datetime import datetime, timedelta

from app.auth.service import create_user, set_membership
from app.config import settings
from app.models import Invite, Organization, OrgMembership, User, UserSession
from app.services.observatory.tenancy import default_organization_id

PW = "correct horse battery"


def _org(db, name="Harbor Bend Partners", slug="harbor-bend"):
    org = Organization(name=name, slug=slug, is_active=True, settings={})
    db.add(org)
    db.commit()
    db.refresh(org)
    return org


def _owner(db, org_id, email="owner@example.com"):
    user = create_user(db, email, PW, "Owner")
    set_membership(db, user, org_id, "owner")
    return user


def _login(client, email, password=PW):
    r = client.post("/api/auth/login", json={"email": email, "password": password})
    assert r.status_code == 200, r.text
    return r.json()["token"]


def _bearer(token, org_id=None):
    h = {"Authorization": f"Bearer {token}"}
    if org_id is not None:
        h["X-Beacon-Org"] = str(org_id)
    return h


def test_open_mode_until_the_first_user_exists(client, db):
    r = client.get("/api/auth/me")
    assert r.status_code == 200 and r.json()["via"] == "open" and r.json()["is_platform_admin"]
    assert client.get("/api/companies").status_code == 200
    create_user(db, "first@example.com", PW)
    assert client.get("/api/auth/me").status_code == 401
    assert client.get("/api/auth/me", headers=_bearer("not-a-token")).status_code == 401


def test_access_key_stays_a_break_glass_credential(client, db, monkeypatch):
    create_user(db, "someone@example.com", PW)
    monkeypatch.setattr(settings, "access_key", "s3cret")
    assert client.get("/api/companies").status_code == 401
    r = client.get("/api/auth/me", headers={"X-Beacon-Key": "s3cret"})
    assert r.status_code == 200 and r.json()["via"] == "access_key" and r.json()["is_platform_admin"]
    # Signing in never needs the key.
    assert client.post("/api/auth/login", json={"email": "someone@example.com", "password": PW}).status_code == 200


def test_login_me_logout_and_lockout(client, db):
    org = _org(db)
    _owner(db, org.id)
    bad = client.post("/api/auth/login", json={"email": "owner@example.com", "password": "nope"})
    assert bad.status_code == 401
    token = _login(client, "OWNER@example.com")
    me = client.get("/api/auth/me", headers=_bearer(token)).json()
    assert me["user"]["email"] == "owner@example.com" and me["via"] == "session"
    assert me["org"]["id"] == org.id and me["org"]["role"] == "owner" and not me["is_platform_admin"]
    assert [m["organization_slug"] for m in me["memberships"]] == ["harbor-bend"]
    assert client.post("/api/auth/logout", headers=_bearer(token)).status_code == 200
    assert client.get("/api/auth/me", headers=_bearer(token)).status_code == 401
    for _ in range(10):
        client.post("/api/auth/login", json={"email": "owner@example.com", "password": "nope"})
    locked = client.post("/api/auth/login", json={"email": "owner@example.com", "password": PW})
    assert locked.status_code == 429


def test_sessions_expire_and_disabled_users_lose_access(client, db):
    org = _org(db)
    user = _owner(db, org.id)
    token = _login(client, user.email)
    sess = db.query(UserSession).filter_by(user_id=user.id).one()
    sess.expires_at = datetime.utcnow() - timedelta(minutes=1)
    db.commit()
    assert client.get("/api/auth/me", headers=_bearer(token)).status_code == 401
    token2 = _login(client, user.email)
    user.is_active = False
    db.commit()
    assert client.get("/api/auth/me", headers=_bearer(token2)).status_code == 401


def test_act_as_org_rules(client, db):
    a = _org(db, "A Co", "a-co")
    b = _org(db, "B Co", "b-co")
    user = _owner(db, a.id)
    token = _login(client, user.email)
    assert client.get("/api/auth/me", headers=_bearer(token, b.id)).status_code == 403
    admin = create_user(db, "tina@example.com", PW, "Tina", is_platform_admin=True)
    at = _login(client, admin.email)
    me = client.get("/api/auth/me", headers=_bearer(at)).json()
    assert me["is_platform_admin"] and me["org"] is None and len(me["organizations"]) >= 3
    me_b = client.get("/api/auth/me", headers=_bearer(at, b.id)).json()
    assert me_b["org"]["id"] == b.id and me_b["org"]["role"] == "platform_admin"
    assert client.get("/api/auth/me", headers=_bearer(at) | {"X-Beacon-Org": "abc"}).status_code == 400


def test_invite_new_user_flow(client, db):
    org = _org(db)
    owner = _owner(db, org.id)
    token = _login(client, owner.email)
    r = client.post("/api/auth/invites", json={"organization_id": org.id, "email": "New.Person@Example.com", "role": "admin"},
                    headers=_bearer(token))
    assert r.status_code == 201, r.text
    body = r.json()
    assert body["delivered"] is False and body["link"].startswith("http://localhost:3100/invite/")
    invite_token = body["link"].rsplit("/", 1)[1]
    public = client.get(f"/api/auth/invites/{invite_token}").json()
    assert public == {"organization_name": "Harbor Bend Partners", "email": "new.person@example.com",
                      "role": "admin", "state": "open", "existing_user": False}
    weak = client.post(f"/api/auth/invites/{invite_token}/accept", json={"name": "New", "password": "short"})
    assert weak.status_code == 422
    accepted = client.post(f"/api/auth/invites/{invite_token}/accept", json={"name": "New Person", "password": PW})
    assert accepted.status_code == 200, accepted.text
    assert accepted.json()["org"]["role"] == "admin"
    again = client.post(f"/api/auth/invites/{invite_token}/accept", json={"name": "New Person", "password": PW})
    assert again.status_code == 410
    members = client.get(f"/api/auth/orgs/{org.id}/members", headers=_bearer(token)).json()
    assert {m["email"]: m["role"] for m in members["members"]} == {"owner@example.com": "owner", "new.person@example.com": "admin"}
    assert members["pending_invites"] == []


def test_invite_existing_user_needs_their_password(client, db):
    a = _org(db, "A Co", "a-co")
    b = _org(db, "B Co", "b-co")
    owner_a = _owner(db, a.id, "owner-a@example.com")
    owner_b = _owner(db, b.id, "owner-b@example.com")
    tb = _login(client, owner_b.email)
    r = client.post("/api/auth/invites", json={"organization_id": b.id, "email": owner_a.email, "role": "viewer"},
                    headers=_bearer(tb))
    invite_token = r.json()["link"].rsplit("/", 1)[1]
    assert client.get(f"/api/auth/invites/{invite_token}").json()["existing_user"] is True
    assert client.post(f"/api/auth/invites/{invite_token}/accept", json={"password": "wrong password!"}).status_code == 401
    ok = client.post(f"/api/auth/invites/{invite_token}/accept", json={"password": PW})
    assert ok.status_code == 200
    roles = {m["organization_slug"]: m["role"] for m in ok.json()["memberships"]}
    assert roles == {"a-co": "owner", "b-co": "viewer"}
    assert db.query(User).filter_by(email=owner_a.email).count() == 1


def test_only_owners_or_platform_admins_invite(client, db):
    org = _org(db)
    viewer = create_user(db, "viewer@example.com", PW)
    set_membership(db, viewer, org.id, "viewer")
    t = _login(client, viewer.email)
    r = client.post("/api/auth/invites", json={"organization_id": org.id, "email": "x@example.com", "role": "viewer"},
                    headers=_bearer(t))
    assert r.status_code == 403
    r = client.post("/api/auth/invites", json={"organization_id": org.id, "email": "x@example.com", "role": "king"},
                    headers=_bearer(_login(client, _owner(db, org.id).email)))
    assert r.status_code == 422


def test_reset_link_flow_revokes_sessions(client, db):
    org = _org(db)
    owner = _owner(db, org.id)
    member = create_user(db, "member@example.com", PW)
    set_membership(db, member, org.id, "viewer")
    member_token = _login(client, member.email)
    owner_token = _login(client, owner.email)
    r = client.post(f"/api/auth/users/{member.id}/reset-link", headers=_bearer(owner_token))
    assert r.status_code == 200 and r.json()["delivered"] is False
    reset_token = r.json()["link"].rsplit("/", 1)[1]
    assert client.get(f"/api/auth/reset/{reset_token}").json() == {"valid": True, "email": "member@example.com"}
    done = client.post(f"/api/auth/reset/{reset_token}/confirm", json={"password": "a brand new passphrase"})
    assert done.status_code == 200
    assert client.get("/api/auth/me", headers=_bearer(member_token)).status_code == 401
    assert client.get(f"/api/auth/reset/{reset_token}").json()["valid"] is False
    assert _login(client, member.email, "a brand new passphrase")
    # Public request never reveals whether the email exists.
    assert client.post("/api/auth/reset/request", json={"email": "nobody@example.com"}).status_code == 200
    assert client.post("/api/auth/reset/request", json={"email": member.email}).json()["delivered"] is False


def test_password_change_keeps_current_session_only(client, db):
    org = _org(db)
    owner = _owner(db, org.id)
    t1 = _login(client, owner.email)
    t2 = _login(client, owner.email)
    r = client.post("/api/auth/password", json={"current_password": PW, "new_password": "another long passphrase"},
                    headers=_bearer(t1))
    assert r.status_code == 200 and r.json()["other_sessions_signed_out"] == 1
    assert client.get("/api/auth/me", headers=_bearer(t1)).status_code == 200
    assert client.get("/api/auth/me", headers=_bearer(t2)).status_code == 401


def test_team_roles_and_last_owner_rule(client, db):
    org = _org(db)
    owner = _owner(db, org.id)
    other = create_user(db, "other@example.com", PW)
    set_membership(db, other, org.id, "admin")
    t = _login(client, owner.email)
    assert client.patch(f"/api/auth/orgs/{org.id}/members/{owner.id}", json={"role": "viewer"},
                        headers=_bearer(t)).status_code == 409
    assert client.delete(f"/api/auth/orgs/{org.id}/members/{owner.id}", headers=_bearer(t)).status_code == 409
    r = client.patch(f"/api/auth/orgs/{org.id}/members/{other.id}", json={"role": "owner"}, headers=_bearer(t))
    assert r.status_code == 200 and r.json()["role"] == "owner"
    assert client.delete(f"/api/auth/orgs/{org.id}/members/{owner.id}", headers=_bearer(t)).status_code == 200
    assert db.query(OrgMembership).filter_by(organization_id=org.id).count() == 1
    # A removed owner can still sign in but has no organization and no role.
    me = client.get("/api/auth/me", headers=_bearer(t))
    assert me.status_code == 200 and me.json()["org"] is None and me.json()["memberships"] == []


def test_create_user_cli_is_idempotent(db, test_sessionmaker, monkeypatch):
    import app.cli.create_user as cli

    monkeypatch.setattr(cli, "SessionLocal", test_sessionmaker)
    assert cli.run(["--email", "Tina@Example.com", "--name", "Tina", "--password", PW, "--platform-admin"]) == 0
    assert cli.run(["--email", "tina@example.com", "--role", "owner"]) == 0
    users = db.query(User).all()
    assert len(users) == 1 and users[0].is_platform_admin and users[0].name == "Tina"
    m = db.query(OrgMembership).filter_by(user_id=users[0].id).one()
    assert m.organization_id == default_organization_id(db) and m.role == "owner"
    assert cli.run(["--email", "x@example.com", "--password", "short"]) == 2


def test_bootstrap_admin_runs_once(db, test_sessionmaker, monkeypatch):
    import app.auth.bootstrap as boot

    monkeypatch.setattr(boot, "SessionLocal", test_sessionmaker)
    monkeypatch.setattr(settings, "bootstrap_admin_email", "founder@example.com")
    monkeypatch.setattr(settings, "bootstrap_admin_password", PW)
    assert boot.bootstrap_admin() is not None
    assert boot.bootstrap_admin() is None
    user = db.query(User).filter_by(email="founder@example.com").one()
    assert user.is_platform_admin
    assert db.query(OrgMembership).filter_by(user_id=user.id, role="owner").count() == 1


def test_migration_backfills_default_org_billing_override(db):
    org = db.query(Organization).filter_by(slug="default").one()
    assert (org.settings or {}).get("billing_override", {}).get("active") is True
    assert db.query(Invite).count() == 0
