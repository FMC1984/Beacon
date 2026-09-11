"""Markets and submarkets (Phase 19, slice 1b).

A Market is shared geography (city + state, slug like "denver-co"), NOT
owned by an organization unless organization_id is set. It is the unit the
Observatory shares observations across: one market prompt is executed once
and scored against every Beacon property in that market (Phase 3). Markets
are created automatically from property city/state; submarkets are
operator-asserted neighborhoods within a market.
"""

from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class Market(Base):
    __tablename__ = "markets"
    __table_args__ = (
        Index("ix_markets_state_city", "state", "city"),
        Index("ix_markets_org", "organization_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # NULL = shared geography visible to every organization.
    organization_id: Mapped[int | None] = mapped_column(ForeignKey("organizations.id"))
    slug: Mapped[str] = mapped_column(String(200), unique=True)
    name: Mapped[str] = mapped_column(String(200))
    city: Mapped[str] = mapped_column(String(100))
    state: Mapped[str] = mapped_column(String(2))
    metro_name: Mapped[str | None] = mapped_column(String(200))
    lat: Mapped[float | None] = mapped_column(Float)
    lng: Mapped[float | None] = mapped_column(Float)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class Submarket(Base):
    __tablename__ = "submarkets"
    __table_args__ = (
        Index("uq_submarkets_market_slug", "market_id", "slug", unique=True),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    market_id: Mapped[int] = mapped_column(ForeignKey("markets.id"))
    slug: Mapped[str] = mapped_column(String(200))
    name: Mapped[str] = mapped_column(String(200))
    neighborhood_aliases: Mapped[list | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
