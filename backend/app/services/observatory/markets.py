"""Market resolution (Phase 19, slice 1b). Markets are shared geography
keyed by city + state; a property is assigned to one automatically from its
own city/state, never inferred from anything else."""

import re

from sqlalchemy.orm import Session

from app.models import Company, Market, Property


def market_slug(city: str, state: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", f"{city}-{state}".lower()).strip("-")


def ensure_market(db: Session, city: str, state: str, organization_id: int | None = None) -> Market:
    slug = market_slug(city, state)
    market = db.query(Market).filter_by(slug=slug).one_or_none()
    if market is None:
        market = Market(
            organization_id=organization_id,
            slug=slug,
            name=f"{city.strip()}, {state.strip().upper()}",
            city=city.strip(),
            state=state.strip().upper(),
            is_active=True,
        )
        db.add(market)
        db.flush()
    return market


def assign_property_market(db: Session, prop: Property) -> Market | None:
    """Set prop.market_id from its city/state (creating the market if new).
    Clears it when the property has no usable city/state. Does not commit."""
    city = (prop.city or "").strip()
    state = (prop.state or "").strip()
    if not city or not state:
        prop.market_id = None
        return None
    market = ensure_market(db, city, state)
    prop.market_id = market.id
    return market


def market_members(
    db: Session, market_id: int, organization_id: int | None = None
) -> list[Property]:
    q = db.query(Property).filter(Property.market_id == market_id, Property.is_active.is_(True))
    if organization_id is not None:
        company_ids = [
            c.id for c in db.query(Company.id).filter(Company.organization_id == organization_id)
        ]
        q = q.filter(Property.company_id.in_(company_ids))
    return q.order_by(Property.name).all()
