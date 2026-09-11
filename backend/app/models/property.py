from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Float, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class Property(Base):
    __tablename__ = "properties"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(200), unique=True)
    slug: Mapped[str] = mapped_column(String(200), unique=True)
    # Alternate names AI responses might use for this property (e.g. "The
    # Collective on 13th" / "Collective on 13th"). Operator-asserted, matched
    # literally alongside `name` - same posture as Competitor.aliases.
    aliases: Mapped[list | None] = mapped_column(JSON)
    # Client/site type (multifamily_apartment | housing_authority). Required;
    # existing rows default to multifamily_apartment. Drives terminology, the
    # Content Intelligence knowledge bases, connectors, and Nora framing. This is
    # SEPARATE from PropertyProfile.property_type (regulatory/marketing type).
    property_type: Mapped[str] = mapped_column(
        String(50), nullable=False, server_default="multifamily_apartment"
    )
    # Optional owning company; null means 'Unassigned'.
    company_id: Mapped[int | None] = mapped_column(ForeignKey("companies.id"))
    external_code: Mapped[str | None] = mapped_column(String(100))
    city: Mapped[str | None] = mapped_column(String(100))
    state: Mapped[str | None] = mapped_column(String(2))
    unit_count: Mapped[int | None] = mapped_column(Integer)
    website_url: Mapped[str | None] = mapped_column(String(1000))
    # --- Phase 19 Observatory attributes. None of these is required. ---
    market_id: Mapped[int | None] = mapped_column(ForeignKey("markets.id"))
    submarket_id: Mapped[int | None] = mapped_column(ForeignKey("submarkets.id"))
    address_line1: Mapped[str | None] = mapped_column(String(200))
    zip: Mapped[str | None] = mapped_column(String(10))
    lat: Mapped[float | None] = mapped_column(Float)
    lng: Mapped[float | None] = mapped_column(Float)
    # Normalized registrable host of website_url (owned-domain matching for
    # citations); may carry a path prefix for shared management-company sites.
    domain: Mapped[str | None] = mapped_column(String(255))
    # Free-form structured facts (amenities[], pet_policy{}, floor_plans[],
    # rent_range{}, neighborhood, segment). Operator-asserted; used for
    # prompt generation and claim verification, never inferred by Beacon.
    attributes: Mapped[dict | None] = mapped_column(JSON)
    management_company: Mapped[str | None] = mapped_column(String(200))
    ownership: Mapped[str | None] = mapped_column(String(200))
    known_competitor_domains: Mapped[list | None] = mapped_column(JSON)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now()
    )
