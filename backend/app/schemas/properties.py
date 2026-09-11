from datetime import datetime

from pydantic import BaseModel, ConfigDict


class _ObservatoryAttributes(BaseModel):
    """Phase 19 property attributes. All optional; never required."""

    address_line1: str | None = None
    zip: str | None = None
    lat: float | None = None
    lng: float | None = None
    submarket_id: int | None = None
    attributes: dict | None = None
    management_company: str | None = None
    ownership: str | None = None
    known_competitor_domains: list[str] | None = None


class PropertyCreate(_ObservatoryAttributes):
    name: str
    slug: str | None = None
    property_type: str = "multifamily_apartment"
    company_id: int | None = None
    external_code: str | None = None
    city: str | None = None
    state: str | None = None
    unit_count: int | None = None
    website_url: str | None = None


class PropertyUpdate(_ObservatoryAttributes):
    name: str | None = None
    property_type: str | None = None
    # company_id is tri-state: omitted = unchanged, null = unassign,
    # int = assign. exclude_unset in the router preserves this distinction.
    company_id: int | None = None
    external_code: str | None = None
    city: str | None = None
    state: str | None = None
    unit_count: int | None = None
    website_url: str | None = None


class PropertyOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    slug: str
    property_type: str
    company_id: int | None
    external_code: str | None
    city: str | None
    state: str | None
    unit_count: int | None
    website_url: str | None
    is_active: bool
    created_at: datetime
    # Phase 19 (derived + optional attributes)
    market_id: int | None = None
    submarket_id: int | None = None
    domain: str | None = None
    address_line1: str | None = None
    zip: str | None = None
    lat: float | None = None
    lng: float | None = None
    attributes: dict | None = None
    management_company: str | None = None
    ownership: str | None = None
    known_competitor_domains: list[str] | None = None
