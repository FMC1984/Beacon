"""Stripe billing state, maintained by webhooks (never by trusting the browser).

One Stripe customer per organization; subscriptions priced per monitored
community (quantity); one-time purchases for the audit; every webhook event
logged once by Stripe event id so redelivery is harmless.
"""

from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base

SUBSCRIPTION_ACTIVE_STATUSES = ("active", "trialing", "past_due")
TIER_STANDARD = "standard"
TIER_ADVANCED = "advanced"
PRODUCT_AUDIT = "audit"


class StripeCustomer(Base):
    __tablename__ = "stripe_customers"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), unique=True)
    stripe_customer_id: Mapped[str] = mapped_column(String(120), unique=True)
    email: Mapped[str | None] = mapped_column(String(320))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class Subscription(Base):
    __tablename__ = "subscriptions"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    stripe_subscription_id: Mapped[str] = mapped_column(String(120), unique=True)
    stripe_customer_id: Mapped[str | None] = mapped_column(String(120))
    status: Mapped[str] = mapped_column(String(40))
    price_id: Mapped[str | None] = mapped_column(String(120))
    tier: Mapped[str | None] = mapped_column(String(20))
    quantity: Mapped[int] = mapped_column(Integer, default=0)
    current_period_end: Mapped[datetime | None] = mapped_column(DateTime)
    cancel_at_period_end: Mapped[bool] = mapped_column(Boolean, default=False)
    last_invoice_status: Mapped[str | None] = mapped_column(String(40))
    raw: Mapped[dict | None] = mapped_column(JSON)
    updated_at: Mapped[datetime | None] = mapped_column(DateTime)


class BillingPurchase(Base):
    __tablename__ = "billing_purchases"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organization_id: Mapped[int] = mapped_column(ForeignKey("organizations.id"), index=True)
    product: Mapped[str] = mapped_column(String(40))
    stripe_checkout_session_id: Mapped[str] = mapped_column(String(160), unique=True)
    amount_cents: Mapped[int | None] = mapped_column(Integer)
    currency: Mapped[str | None] = mapped_column(String(10))
    paid_at: Mapped[datetime | None] = mapped_column(DateTime)


class BillingEvent(Base):
    __tablename__ = "billing_events"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    stripe_event_id: Mapped[str] = mapped_column(String(120), unique=True)
    type: Mapped[str] = mapped_column(String(80))
    organization_id: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20))
    error: Mapped[str | None] = mapped_column(Text)
    payload: Mapped[dict | None] = mapped_column(JSON)
    received_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    processed_at: Mapped[datetime | None] = mapped_column(DateTime)
