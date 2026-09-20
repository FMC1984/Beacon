"""The only module that talks to Stripe. Tests monkeypatch these functions;
nothing else in the app imports `stripe` directly."""

from app.config import settings


class BillingNotConfigured(Exception):
    pass


def configured() -> bool:
    return bool(settings.stripe_secret_key)


def _stripe():
    if not configured():
        raise BillingNotConfigured("Billing is not configured on this server (no Stripe key).")
    import stripe

    stripe.api_key = settings.stripe_secret_key
    return stripe


def create_customer(email: str | None, name: str, organization_id: int) -> str:
    customer = _stripe().Customer.create(
        email=email or None, name=name, metadata={"organization_id": str(organization_id)}
    )
    return customer["id"]


def create_checkout_session(*, customer_id: str, mode: str, price_id: str, quantity: int,
                            organization_id: int, success_url: str, cancel_url: str, product: str) -> str:
    stripe = _stripe()
    params: dict = {
        "mode": mode,
        "customer": customer_id,
        "line_items": [{"price": price_id, "quantity": quantity}],
        "success_url": success_url,
        "cancel_url": cancel_url,
        "client_reference_id": str(organization_id),
        "allow_promotion_codes": True,
        "metadata": {"organization_id": str(organization_id), "product": product},
    }
    if mode == "subscription":
        params["subscription_data"] = {"metadata": {"organization_id": str(organization_id), "tier": product}}
    session = stripe.checkout.Session.create(**params)
    return session["url"]


def create_portal_session(customer_id: str, return_url: str) -> str:
    session = _stripe().billing_portal.Session.create(customer=customer_id, return_url=return_url)
    return session["url"]


def retrieve_subscription(subscription_id: str) -> dict:
    return _stripe().Subscription.retrieve(subscription_id)


def update_subscription_quantity(subscription_id: str, quantity: int) -> dict:
    stripe = _stripe()
    sub = stripe.Subscription.retrieve(subscription_id)
    item_id = sub["items"]["data"][0]["id"]
    return stripe.Subscription.modify(
        subscription_id, items=[{"id": item_id, "quantity": quantity}], proration_behavior="create_prorations"
    )


def construct_event(payload: bytes, signature_header: str) -> dict:
    """Verify the webhook signature and return the event as a plain dict."""
    if not settings.stripe_webhook_secret:
        raise BillingNotConfigured("Billing webhooks are not configured (no signing secret).")
    import json

    import stripe

    # construct_event verifies the signature (raising on any mismatch); the
    # verified raw body is then the cleanest source of a plain dict.
    stripe.Webhook.construct_event(payload, signature_header, settings.stripe_webhook_secret)
    return json.loads(payload)
