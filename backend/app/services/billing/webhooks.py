"""Stripe webhook handling: log every event once by id, then update local
billing state. DB-only, runs inline in the request, never calls Stripe."""

from datetime import datetime

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import BillingEvent, BillingPurchase, StripeCustomer, Subscription
from app.models.billing import PRODUCT_AUDIT
from app.services.billing.entitlement import tier_for_price

HANDLED = {
    "checkout.session.completed",
    "customer.subscription.created",
    "customer.subscription.updated",
    "customer.subscription.deleted",
    "invoice.paid",
    "invoice.payment_failed",
}

STATUS_PROCESSED = "processed"
STATUS_IGNORED = "ignored"
STATUS_FAILED = "failed"
STATUS_DUPLICATE = "duplicate"


def _org_from_customer(db: Session, customer_id: str | None) -> int | None:
    if not customer_id:
        return None
    row = db.query(StripeCustomer).filter_by(stripe_customer_id=customer_id).first()
    return row.organization_id if row else None


def _org_from_metadata(meta: dict | None) -> int | None:
    raw = (meta or {}).get("organization_id")
    try:
        return int(raw) if raw not in (None, "") else None
    except (TypeError, ValueError):
        return None


def _ts(value) -> datetime | None:
    if value in (None, "", 0):
        return None
    try:
        return datetime.utcfromtimestamp(int(value))
    except (TypeError, ValueError, OverflowError):
        return None


def _ensure_customer(db: Session, organization_id: int | None, customer_id: str | None, email: str | None) -> None:
    if organization_id is None or not customer_id:
        return
    existing = db.query(StripeCustomer).filter_by(organization_id=organization_id).first()
    if existing is None:
        db.add(StripeCustomer(organization_id=organization_id, stripe_customer_id=customer_id, email=email))
    elif existing.stripe_customer_id != customer_id:
        existing.stripe_customer_id = customer_id


def _upsert_subscription(db: Session, sub: dict) -> int | None:
    items = ((sub.get("items") or {}).get("data") or [])
    first = items[0] if items else {}
    price = (first.get("price") or {})
    price_id = price.get("id") if isinstance(price, dict) else price
    customer = sub.get("customer")
    customer_id = customer if isinstance(customer, str) else (customer or {}).get("id")
    organization_id = _org_from_metadata(sub.get("metadata")) or _org_from_customer(db, customer_id)
    if organization_id is None:
        return None
    row = db.query(Subscription).filter_by(stripe_subscription_id=sub["id"]).first()
    if row is None:
        row = Subscription(organization_id=organization_id, stripe_subscription_id=sub["id"], status="incomplete")
        db.add(row)
    row.organization_id = organization_id
    row.stripe_customer_id = customer_id
    row.status = sub.get("status") or row.status
    row.price_id = price_id
    row.tier = tier_for_price(price_id) or (sub.get("metadata") or {}).get("tier")
    row.quantity = int(first.get("quantity") or 0)
    row.current_period_end = _ts(sub.get("current_period_end") or first.get("current_period_end"))
    row.cancel_at_period_end = bool(sub.get("cancel_at_period_end"))
    row.raw = {k: sub.get(k) for k in ("id", "status", "customer", "metadata", "cancel_at_period_end")}
    row.updated_at = datetime.utcnow()
    _ensure_customer(db, organization_id, customer_id, None)
    return organization_id


def _handle_checkout(db: Session, session: dict) -> int | None:
    organization_id = _org_from_metadata(session.get("metadata"))
    if organization_id is None and session.get("client_reference_id"):
        try:
            organization_id = int(session["client_reference_id"])
        except ValueError:
            organization_id = None
    customer = session.get("customer")
    customer_id = customer if isinstance(customer, str) else (customer or {}).get("id")
    email = (session.get("customer_details") or {}).get("email")
    _ensure_customer(db, organization_id, customer_id, email)
    if session.get("mode") == "payment" and organization_id is not None:
        if db.query(BillingPurchase).filter_by(stripe_checkout_session_id=session["id"]).first() is None:
            db.add(BillingPurchase(
                organization_id=organization_id,
                product=(session.get("metadata") or {}).get("product") or PRODUCT_AUDIT,
                stripe_checkout_session_id=session["id"],
                amount_cents=session.get("amount_total"),
                currency=session.get("currency"),
                paid_at=datetime.utcnow() if session.get("payment_status") == "paid" else None,
            ))
    return organization_id


def _handle_invoice(db: Session, invoice: dict, status: str) -> int | None:
    sub_id = invoice.get("subscription")
    if not sub_id:
        sub_id = (((invoice.get("parent") or {}).get("subscription_details") or {}).get("subscription"))
    if isinstance(sub_id, dict):
        sub_id = sub_id.get("id")
    if not sub_id:
        return None
    row = db.query(Subscription).filter_by(stripe_subscription_id=sub_id).first()
    if row is None:
        return None
    row.last_invoice_status = status
    row.updated_at = datetime.utcnow()
    return row.organization_id


def handle_event(db: Session, event: dict) -> BillingEvent:
    """Idempotent: a redelivered event id is logged as duplicate and skipped."""
    event_id = event.get("id") or ""
    event_type = event.get("type") or ""
    log = BillingEvent(stripe_event_id=event_id, type=event_type, status=STATUS_IGNORED,
                       payload={"type": event_type, "object": (event.get("data") or {}).get("object", {}).get("id")})
    db.add(log)
    try:
        db.flush()
    except IntegrityError:
        db.rollback()
        dup = BillingEvent(stripe_event_id=f"{event_id}:dup:{datetime.utcnow().timestamp()}", type=event_type,
                           status=STATUS_DUPLICATE, payload={"duplicate_of": event_id})
        db.add(dup)
        db.commit()
        return dup
    obj = (event.get("data") or {}).get("object") or {}
    try:
        organization_id = None
        if event_type == "checkout.session.completed":
            organization_id = _handle_checkout(db, obj)
        elif event_type in ("customer.subscription.created", "customer.subscription.updated",
                            "customer.subscription.deleted"):
            organization_id = _upsert_subscription(db, obj)
        elif event_type == "invoice.paid":
            organization_id = _handle_invoice(db, obj, "paid")
        elif event_type == "invoice.payment_failed":
            organization_id = _handle_invoice(db, obj, "payment_failed")
        log.organization_id = organization_id
        log.status = STATUS_PROCESSED if event_type in HANDLED else STATUS_IGNORED
        log.processed_at = datetime.utcnow()
        db.commit()
    except Exception as exc:  # never lose the event log over a handler bug
        db.rollback()
        log = db.merge(BillingEvent(stripe_event_id=event_id, type=event_type, status=STATUS_FAILED,
                                    error=str(exc)[:2000], payload={"type": event_type}))
        db.commit()
    return log
