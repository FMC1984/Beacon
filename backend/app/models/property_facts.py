"""Provenance for the facts Beacon holds about a property (Truth layer v1).

The fact VALUES stay where they already live (Property.attributes and
Property Context), so there is one place to edit them. This table records
what makes a value trustworthy: who says so, when it was last verified, when
it took effect, and how quickly it goes stale. One row per (property, fact).
"""

from datetime import date, datetime

from sqlalchemy import Date, DateTime, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base

FRESH_STABLE = "stable"      # amenities, pet policy, property type
FRESH_SEASONAL = "seasonal"  # specials, fees that change a few times a year
FRESH_VOLATILE = "volatile"  # rent and availability: needs a live feed, never graded as a conflict
FRESHNESS = (FRESH_STABLE, FRESH_SEASONAL, FRESH_VOLATILE)
# Days after which a verification is considered stale.
STALE_AFTER = {FRESH_STABLE: 180, FRESH_SEASONAL: 90, FRESH_VOLATILE: 7}


class PropertyFact(Base):
    __tablename__ = "property_facts"
    __table_args__ = (Index("uq_property_facts_key", "property_id", "fact_key", unique=True),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organization_id: Mapped[int | None] = mapped_column(Integer)
    property_id: Mapped[int] = mapped_column(ForeignKey("properties.id"))
    fact_key: Mapped[str] = mapped_column(String(80))
    source_of_truth: Mapped[str | None] = mapped_column(String(200))
    verified_at: Mapped[datetime | None] = mapped_column(DateTime)
    verified_by: Mapped[str | None] = mapped_column(String(120))
    effective_date: Mapped[date | None] = mapped_column(Date)
    freshness: Mapped[str] = mapped_column(String(20), default=FRESH_STABLE)
    notes: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime | None] = mapped_column(DateTime)
