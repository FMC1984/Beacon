"""Operator-asserted property context (1:1 with Property).

Durable, property-specific metadata that downstream analysis reads on nearly
every run: property type, target audience, regulatory status, and marketing
restrictions. Program and regulatory status is ALWAYS operator-provided; Beacon
never infers it from reviews, names, amenities, or content.

Every field tolerates being unset. `is_regulated` is nullable and null means
UNKNOWN (never treated as "not regulated"). Allowed values for property_type /
regulatory_programs / restriction flags live in
reference_data/property_context.json, so the vocabulary changes without a
migration; only the per-property assignment lives on this row.

Deferred by scope (Competitor Intelligence, a later phase): property class,
physical type, market positioning, unit mix. The schema does not preclude them.
"""

from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class PropertyProfile(Base):
    __tablename__ = "property_profile"
    __table_args__ = (
        UniqueConstraint("property_id", name="uq_property_profile_property"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    property_id: Mapped[int] = mapped_column(ForeignKey("properties.id"), index=True)
    property_type: Mapped[str | None] = mapped_column(String(50))
    target_audience: Mapped[str | None] = mapped_column(String(500))
    # null = UNKNOWN (never "not regulated").
    is_regulated: Mapped[bool | None] = mapped_column(Boolean)
    regulatory_programs: Mapped[list | None] = mapped_column(JSON)
    marketing_restriction_flags: Mapped[list | None] = mapped_column(JSON)
    marketing_restriction_notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now()
    )
    updated_at: Mapped[datetime | None] = mapped_column(DateTime)
