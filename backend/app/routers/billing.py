"""Billing: Stripe Checkout, the Customer Portal, status, and the webhook."""

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel
from sqlalchemy.orm import Session

from app.auth.deps import Principal, current_principal, require_role
from app.config import settings
from app.db import get_db
from app.models import Organization, StripeCustomer
from app.models.billing import PRODUCT_AUDIT, TIER_ADVANCED, TIER_STANDARD
from app.services.billing import stripe_client
from app.services.billing.entitlement import entitlement, monitored_count
from app.services.billing.webhooks import handle_event

router = APIRouter(prefix="/billing", tags=["billing"])


class CheckoutIn(BaseModel):
    product: str  # standard | advanced | audit
    quantity: int | None = None


def _org_or_422(db: Session, principal: Principal) -> Organization:
    if principal.org_id is None:
        raise HTTPException(status_code=422, detail="Choose an organization first (X-Beacon-Org).")
    org = db.get(Organization, principal.org_id)
    if org is None:
        raise HTTPException(status_code=404, detail="Organization not found.")
    return org


def _price_for(product: str) -> tuple[str, str]:
    if product == TIER_STANDARD:
        return settings.stripe_price_standard, "subscription"
    if product == TIER_ADVANCED:
        return settings.stripe_price_advanced, "subscription"
    if product == PRODUCT_AUDIT:
        return settings.stripe_price_audit, "payment"
    raise HTTPException(status_code=422, detail="product must be standard, advanced or audit.")


def _return_url() -> str:
    return settings.stripe_portal_return_url or f"{settings.frontend_url.rstrip('/')}/settings/billing"


@router.get("/status", dependencies=[Depends(require_role("viewer"))])
def billing_status(db: Session = Depends(get_db), principal: Principal = Depends(current_principal)):
    if principal.org_id is None:
        return {"configured": stripe_client.configured(), "organization_id": None, "entitlement": None,
                "prices": _prices(), "note": "Pick an organization to see its billing."}
    ent = entitlement(db, principal.org_id)
    customer = db.query(StripeCustomer).filter_by(organization_id=principal.org_id).first()
    return {
        "configured": stripe_client.configured(),
        "organization_id": principal.org_id,
        "entitlement": ent.to_dict(),
        "has_customer": customer is not None,
        "prices": _prices(),
        "auto_quantity": settings.stripe_auto_quantity,
    }


def _prices() -> dict:
    return {
        "standard": bool(settings.stripe_price_standard),
        "advanced": bool(settings.stripe_price_advanced),
        "audit": bool(settings.stripe_price_audit),
    }


@router.post("/checkout", dependencies=[Depends(require_role("owner"))])
def checkout(payload: CheckoutIn, db: Session = Depends(get_db), principal: Principal = Depends(current_principal)):
    org = _org_or_422(db, principal)
    if not stripe_client.configured():
        raise HTTPException(status_code=503, detail="Billing is not configured on this server yet.")
    price_id, mode = _price_for(payload.product)
    if not price_id:
        raise HTTPException(status_code=503, detail=f"No Stripe price is configured for {payload.product}.")
    quantity = payload.quantity if mode == "subscription" else 1
    if mode == "subscription":
        if quantity is None:
            quantity = max(1, monitored_count(db, org.id))
        if quantity < 1:
            raise HTTPException(status_code=422, detail="Quantity must be at least 1.")
    customer = db.query(StripeCustomer).filter_by(organization_id=org.id).first()
    try:
        if customer is None:
            email = principal.user.email if principal.user else None
            cid = stripe_client.create_customer(email, org.name, org.id)
            customer = StripeCustomer(organization_id=org.id, stripe_customer_id=cid, email=email)
            db.add(customer)
            db.commit()
        url = stripe_client.create_checkout_session(
            customer_id=customer.stripe_customer_id, mode=mode, price_id=price_id, quantity=quantity,
            organization_id=org.id, success_url=_return_url() + "?checkout=success",
            cancel_url=_return_url() + "?checkout=cancelled", product=payload.product,
        )
    except stripe_client.BillingNotConfigured as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    return {"url": url, "mode": mode, "quantity": quantity}


@router.post("/portal", dependencies=[Depends(require_role("owner"))])
def portal(db: Session = Depends(get_db), principal: Principal = Depends(current_principal)):
    org = _org_or_422(db, principal)
    customer = db.query(StripeCustomer).filter_by(organization_id=org.id).first()
    if customer is None:
        raise HTTPException(status_code=404, detail="No billing account yet. Start a subscription first.")
    try:
        url = stripe_client.create_portal_session(customer.stripe_customer_id, _return_url())
    except stripe_client.BillingNotConfigured as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    return {"url": url}


@router.post("/sync-quantity", dependencies=[Depends(require_role("owner"))])
def sync_quantity(db: Session = Depends(get_db), principal: Principal = Depends(current_principal)):
    org = _org_or_422(db, principal)
    ent = entitlement(db, org.id)
    if not ent.subscription_id or ent.source != "subscription":
        raise HTTPException(status_code=409, detail="No active subscription to update.")
    quantity = max(1, ent.monitored)
    try:
        stripe_client.update_subscription_quantity(ent.subscription_id, quantity)
    except stripe_client.BillingNotConfigured as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    return {"subscription_id": ent.subscription_id, "quantity": quantity,
            "note": "Stripe will confirm the change by webhook; the status updates then."}


@router.post("/webhook")
async def webhook(request: Request, db: Session = Depends(get_db)):
    """PUBLIC route: Stripe signs every delivery; the signature is the auth."""
    payload = await request.body()
    signature = request.headers.get("stripe-signature", "")
    try:
        event = stripe_client.construct_event(payload, signature)
    except stripe_client.BillingNotConfigured as exc:
        raise HTTPException(status_code=503, detail=str(exc))
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid Stripe signature.")
    log = handle_event(db, event)
    return {"received": True, "status": log.status, "type": log.type}
