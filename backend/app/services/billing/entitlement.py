"""What an organization is entitled to, from local state only (never a live
Stripe call). Soft by design: over-quantity is reported, not enforced; the
one hard consequence (no active subscription and no override) is read-only."""

from dataclasses import asdict, dataclass
from datetime import datetime

from sqlalchemy.orm import Session

from app.config import settings
from app.models import Organization, Property, Subscription
from app.models.billing import SUBSCRIPTION_ACTIVE_STATUSES, TIER_ADVANCED, TIER_STANDARD
from app.services.observatory.tenancy import org_property_ids

SOURCE_SUBSCRIPTION = "subscription"
SOURCE_OVERRIDE = "override"
SOURCE_SAMPLE = "sample"
SOURCE_NONE = "none"


@dataclass
class Entitlement:
    organization_id: int
    active: bool
    source: str
    plan: str | None
    status: str | None
    quantity: int
    monitored: int
    over_by: int
    under_by: int
    override: bool
    override_reason: str | None
    current_period_end: datetime | None
    cancel_at_period_end: bool
    configured: bool
    subscription_id: str | None = None

    def to_dict(self) -> dict:
        d = asdict(self)
        d["current_period_end"] = self.current_period_end.isoformat() if self.current_period_end else None
        return d


def tier_for_price(price_id: str | None) -> str | None:
    if not price_id:
        return None
    if price_id == settings.stripe_price_advanced:
        return TIER_ADVANCED
    if price_id == settings.stripe_price_standard:
        return TIER_STANDARD
    return None


def monitored_count(db: Session, organization_id: int) -> int:
    ids = org_property_ids(db, organization_id)
    if not ids:
        return 0
    rows = db.query(Property.attributes).filter(Property.id.in_(ids)).all()
    return sum(1 for (attrs,) in rows if not (attrs or {}).get("sample_data"))


def current_subscription(db: Session, organization_id: int) -> Subscription | None:
    rows = db.query(Subscription).filter_by(organization_id=organization_id).all()
    if not rows:
        return None
    rows.sort(key=lambda s: (s.status in SUBSCRIPTION_ACTIVE_STATUSES, s.updated_at or datetime.min), reverse=True)
    return rows[0]


def entitlement(db: Session, organization_id: int) -> Entitlement:
    org = db.get(Organization, organization_id)
    org_settings = (org.settings or {}) if org else {}
    override = org_settings.get("billing_override") or {}
    override_active = bool(override.get("active"))
    is_sample = bool(org_settings.get("sample_data"))
    sub = current_subscription(db, organization_id)
    monitored = monitored_count(db, organization_id)
    quantity = sub.quantity if sub else 0
    sub_active = bool(sub and sub.status in SUBSCRIPTION_ACTIVE_STATUSES)
    if sub_active:
        source = SOURCE_SUBSCRIPTION
    elif override_active:
        source = SOURCE_OVERRIDE
    elif is_sample:
        source = SOURCE_SAMPLE
    else:
        source = SOURCE_NONE
    active = sub_active or override_active or is_sample
    return Entitlement(
        organization_id=organization_id,
        active=active,
        source=source,
        plan=(sub.tier or tier_for_price(sub.price_id)) if sub else None,
        status=sub.status if sub else None,
        quantity=quantity,
        monitored=monitored,
        over_by=max(0, monitored - quantity) if sub_active else 0,
        under_by=max(0, quantity - monitored) if sub_active else 0,
        override=override_active,
        override_reason=override.get("reason") if override_active else None,
        current_period_end=sub.current_period_end if sub else None,
        cancel_at_period_end=bool(sub.cancel_at_period_end) if sub else False,
        configured=bool(settings.stripe_secret_key),
        subscription_id=sub.stripe_subscription_id if sub else None,
    )
