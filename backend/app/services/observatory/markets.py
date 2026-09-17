"""Market resolution (Phase 19, slice 1b). Markets are shared geography
keyed by city + state; a property is assigned to one automatically from its
own city/state, never inferred from anything else."""

import re

from sqlalchemy.orm import Session

from app.models import Submarket, Company, Market, Property


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


def submarket_slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-")


def ensure_submarket(db: Session, market_id: int, name: str) -> Submarket:
    slug = submarket_slug(name)
    sm = db.query(Submarket).filter_by(market_id=market_id, slug=slug).one_or_none()
    if sm is None:
        sm = Submarket(market_id=market_id, slug=slug, name=name.strip())
        db.add(sm)
        db.flush()
    return sm


def assign_property_submarket(db: Session, prop: Property) -> Submarket | None:
    """Set prop.submarket_id from the operator-asserted neighborhood
    (Property attributes). Never inferred from content or reviews. Clears
    it when there is no neighborhood or no market. Does not commit."""
    name = ((prop.attributes or {}).get("neighborhood") or "").strip()
    if not name or prop.market_id is None:
        prop.submarket_id = None
        return None
    sm = ensure_submarket(db, prop.market_id, name)
    prop.submarket_id = sm.id
    return sm


def market_members(
    db: Session, market_id: int, organization_id: int | None = None
) -> list[Property]:
    q = db.query(Property).filter(Property.market_id == market_id, Property.is_active.is_(True))
    if organization_id is not None:
        # Same rule as org_property_ids: unassigned properties belong to the
        # default organization, so scoping a market never silently drops them.
        from app.services.observatory.tenancy import org_property_ids

        q = q.filter(Property.id.in_(org_property_ids(db, organization_id) or [-1]))
    return q.order_by(Property.name).all()
