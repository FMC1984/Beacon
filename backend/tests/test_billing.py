"""Stripe billing without Stripe: the client is faked, webhooks are signed with
the test secret, and entitlement is read from local state only."""

import json
import time

import pytest
import stripe

from app.auth.service import create_user, set_membership
from app.config import settings
from app.models import BillingEvent, BillingPurchase, Organization, StripeCustomer, Subscription
from app.services.billing import stripe_client
from app.services.billing.entitlement import entitlement
from app.services.billing.webhooks import handle_event

PW = "correct horse battery"
SECRET = "whsec_test_secret"


def _org(db, slug="acme", **settings_extra):
    org = Organization(name=slug.upper(), slug=slug, is_active=True, settings=dict(settings_extra))
    db.add(org)
    db.commit()
    db.refresh(org)
    return org


def _owner(client, db, org, email="owner@acme.example"):
    user = create_user(db, email, PW)
    set_membership(db, user, org.id, "owner")
    r = client.post("/api/auth/login", json={"email": email, "password": PW})
    return {"Authorization": f"Bearer {r.json()['token']}", "X-CiteRoll-Org": str(org.id)}


def _signed(payload: dict) -> tuple[bytes, str]:
    body = json.dumps(payload).encode()
    ts = int(time.time())
    sig = stripe.WebhookSignature._compute_signature(f"{ts}.{body.decode()}", SECRET)
    return body, f"t={ts},v1={sig}"


def _sub_event(event_id, sub_id, org_id, status="active", quantity=3, price="price_std", event_type="customer.subscription.created"):
    return {
        "id": event_id, "type": event_type,
        "data": {"object": {
            "id": sub_id, "object": "subscription", "status": status, "customer": "cus_123",
            "cancel_at_period_end": False, "metadata": {"organization_id": str(org_id), "tier": "standard"},
            "items": {"data": [{"id": "si_1", "quantity": quantity, "price": {"id": price},
                                "current_period_end": int(time.time()) + 30 * 86400}]},
        }},
    }


@pytest.fixture(autouse=True)
def _billing_settings(monkeypatch):
    monkeypatch.setattr(settings, "stripe_secret_key", "sk_test_x")
    monkeypatch.setattr(settings, "stripe_webhook_secret", SECRET)
    monkeypatch.setattr(settings, "stripe_price_standard", "price_std")
    monkeypatch.setattr(settings, "stripe_price_advanced", "price_adv")
    monkeypatch.setattr(settings, "stripe_price_audit", "price_audit")


@pytest.fixture()
def fake_stripe(monkeypatch):
    calls = {"customers": [], "checkouts": [], "portals": [], "quantity": []}
    monkeypatch.setattr(stripe_client, "create_customer", lambda email, name, org_id: (calls["customers"].append((email, name, org_id)) or "cus_new"))
    monkeypatch.setattr(stripe_client, "create_checkout_session",
                        lambda **kw: (calls["checkouts"].append(kw) or f"https://checkout.stripe.test/{kw['mode']}"))
    monkeypatch.setattr(stripe_client, "create_portal_session",
                        lambda cid, url: (calls["portals"].append((cid, url)) or "https://portal.stripe.test/x"))
    monkeypatch.setattr(stripe_client, "update_subscription_quantity",
                        lambda sid, q: (calls["quantity"].append((sid, q)) or {"id": sid}))
    return calls


def test_status_and_checkout_for_an_owner(client, db, fake_stripe):
    org = _org(db)
    h = _owner(client, db, org)
    status = client.get("/api/billing/status", headers=h).json()
    assert status["configured"] is True and status["entitlement"]["active"] is False
    assert status["entitlement"]["source"] == "none" and status["has_customer"] is False
    r = client.post("/api/billing/checkout", json={"product": "standard", "quantity": 4}, headers=h)
    assert r.status_code == 200, r.text
    assert r.json() == {"url": "https://checkout.stripe.test/subscription", "mode": "subscription", "quantity": 4}
    assert fake_stripe["customers"] == [("owner@acme.example", "ACME", org.id)]
    kw = fake_stripe["checkouts"][0]
    assert kw["price_id"] == "price_std" and kw["quantity"] == 4 and kw["organization_id"] == org.id
    assert db.query(StripeCustomer).filter_by(organization_id=org.id).one().stripe_customer_id == "cus_new"
    # Audit is a one-time payment; the customer is reused.
    r = client.post("/api/billing/checkout", json={"product": "audit"}, headers=h)
    assert r.json()["mode"] == "payment" and len(fake_stripe["customers"]) == 1
    assert client.post("/api/billing/portal", headers=h).json()["url"] == "https://portal.stripe.test/x"


def test_checkout_needs_owner_and_configuration(client, db, fake_stripe, monkeypatch):
    org = _org(db, billing_override={"active": True})
    viewer = create_user(db, "viewer@acme.example", PW)
    set_membership(db, viewer, org.id, "viewer")
    r = client.post("/api/auth/login", json={"email": viewer.email, "password": PW})
    hv = {"Authorization": f"Bearer {r.json()['token']}"}
    assert client.post("/api/billing/checkout", json={"product": "standard"}, headers=hv).status_code == 403
    assert client.get("/api/billing/status", headers=hv).status_code == 200
    h = _owner(client, db, org)
    assert client.post("/api/billing/checkout", json={"product": "gold"}, headers=h).status_code == 422
    monkeypatch.setattr(settings, "stripe_secret_key", "")
    assert client.post("/api/billing/checkout", json={"product": "standard"}, headers=h).status_code == 503
    assert client.get("/api/billing/status", headers=h).json()["configured"] is False


def test_webhook_signature_and_subscription_lifecycle(client, db):
    org = _org(db)
    body, sig = _signed(_sub_event("evt_1", "sub_1", org.id, quantity=3))
    bad = client.post("/api/billing/webhook", content=body, headers={"stripe-signature": "t=1,v1=nope"})
    assert bad.status_code == 400
    ok = client.post("/api/billing/webhook", content=body, headers={"stripe-signature": sig})
    assert ok.status_code == 200 and ok.json()["status"] == "processed"
    sub = db.query(Subscription).filter_by(stripe_subscription_id="sub_1").one()
    assert sub.organization_id == org.id and sub.status == "active" and sub.quantity == 3 and sub.tier == "standard"
    assert db.query(StripeCustomer).filter_by(organization_id=org.id).one().stripe_customer_id == "cus_123"
    ent = entitlement(db, org.id)
    assert ent.active and ent.source == "subscription" and ent.plan == "standard" and ent.quantity == 3
    # Redelivery is a no-op.
    again = client.post("/api/billing/webhook", content=body, headers={"stripe-signature": sig})
    assert again.json()["status"] == "duplicate"
    assert db.query(Subscription).count() == 1
    # Cancellation flips entitlement off.
    body2, sig2 = _signed(_sub_event("evt_2", "sub_1", org.id, status="canceled", event_type="customer.subscription.deleted"))
    assert client.post("/api/billing/webhook", content=body2, headers={"stripe-signature": sig2}).json()["status"] == "processed"
    db.expire_all()
    assert entitlement(db, org.id).active is False
    assert {e.status for e in db.query(BillingEvent).all()} == {"processed", "duplicate"}


def test_checkout_completed_records_audit_purchase_and_invoice_status(db):
    org = _org(db)
    handle_event(db, {"id": "evt_c", "type": "checkout.session.completed", "data": {"object": {
        "id": "cs_1", "mode": "payment", "customer": "cus_9", "client_reference_id": str(org.id),
        "amount_total": 75000, "currency": "usd", "payment_status": "paid",
        "metadata": {"organization_id": str(org.id), "product": "audit"},
        "customer_details": {"email": "buyer@acme.example"},
    }}})
    p = db.query(BillingPurchase).one()
    assert p.organization_id == org.id and p.product == "audit" and p.amount_cents == 75000 and p.paid_at is not None
    assert db.query(StripeCustomer).filter_by(organization_id=org.id).one().email == "buyer@acme.example"
    handle_event(db, _sub_event("evt_s", "sub_9", org.id, price="price_adv"))
    handle_event(db, {"id": "evt_i", "type": "invoice.payment_failed",
                      "data": {"object": {"id": "in_1", "parent": {"subscription_details": {"subscription": "sub_9"}}}}})
    sub = db.query(Subscription).filter_by(stripe_subscription_id="sub_9").one()
    assert sub.tier == "advanced" and sub.last_invoice_status == "payment_failed"
    unknown = handle_event(db, {"id": "evt_u", "type": "charge.refunded", "data": {"object": {"id": "ch_1"}}})
    assert unknown.status == "ignored"


def test_entitlement_counts_only_real_monitored_communities(client, db, fake_stripe):
    from app.models import Company, Property

    org = _org(db)
    company = Company(name="Acme Co", slug="acme-co", organization_id=org.id)
    db.add(company)
    db.commit()
    for i in range(3):
        db.add(Property(name=f"P{i}", slug=f"p{i}", company_id=company.id,
                        attributes={"sample_data": True} if i == 2 else None))
    db.commit()
    handle_event(db, _sub_event("evt_q", "sub_q", org.id, quantity=1))
    ent = entitlement(db, org.id)
    assert ent.monitored == 2 and ent.quantity == 1 and ent.over_by == 1 and ent.active
    h = _owner(client, db, org)
    r = client.post("/api/billing/sync-quantity", headers=h)
    assert r.status_code == 200 and fake_stripe["quantity"] == [("sub_q", 2)]


def test_override_and_sample_orgs_are_active_without_stripe(db):
    paid = _org(db, "paid", billing_override={"active": True, "reason": "founding client"})
    sample = _org(db, "sample", sample_data=True)
    bare = _org(db, "bare")
    assert entitlement(db, paid.id).source == "override" and entitlement(db, paid.id).override_reason == "founding client"
    assert entitlement(db, sample.id).source == "sample" and entitlement(db, sample.id).active
    assert entitlement(db, bare.id).active is False


def test_platform_admin_manages_orgs_and_overrides(client, db):
    tina = create_user(db, "tina@example.com", PW, is_platform_admin=True)
    r = client.post("/api/auth/login", json={"email": tina.email, "password": PW})
    h = {"Authorization": f"Bearer {r.json()['token']}"}
    created = client.post("/api/admin/orgs", json={"name": "Harbor Bend Partners"}, headers=h)
    assert created.status_code == 201 and created.json()["slug"] == "harbor-bend-partners"
    oid = created.json()["id"]
    assert client.post("/api/admin/orgs", json={"name": "Harbor Bend Partners"}, headers=h).status_code == 409
    patched = client.patch(f"/api/admin/orgs/{oid}", json={"billing_override": {"active": True, "reason": "audit"}}, headers=h)
    assert patched.json()["entitlement"]["source"] == "override"
    org = db.get(Organization, oid)
    db.refresh(org)
    assert org.settings["billing_override"]["reason"] == "audit"
    cleared = client.patch(f"/api/admin/orgs/{oid}", json={"clear_billing_override": True, "is_active": False}, headers=h)
    assert cleared.json()["billing_override"] is None and cleared.json()["is_active"] is False
    listing = client.get("/api/admin/orgs", headers=h).json()["organizations"]
    assert any(o["id"] == oid for o in listing)
    # A regular owner cannot reach org administration.
    other = _org(db, "other")
    ho = _owner(client, db, other)
    assert client.get("/api/admin/orgs", headers=ho).status_code == 403
