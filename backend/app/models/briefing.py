"""Monthly Strategic Briefing snapshots (Phase 17A).

A briefing is a point-in-time synthesis for one property and one calendar
month. It is FROZEN on generation: the stored `payload` is the composed
briefing exactly as it read when generated, so a month's briefing never
silently changes when data later re-syncs. The live endpoint recomposes on
demand; generating persists a snapshot that powers Reports History.
"""

from datetime import date, datetime

from sqlalchemy import JSON, Date, DateTime, ForeignKey, Index, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class MonthlyBriefing(Base):
    __tablename__ = "monthly_briefings"
    __table_args__ = (
        Index("ix_briefing_property_period", "property_id", "period_start"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    property_id: Mapped[int] = mapped_column(ForeignKey("properties.id"))
    period_start: Mapped[date] = mapped_column(Date)
    period_end: Mapped[date] = mapped_column(Date)
    # The composed briefing JSON, frozen at generation time.
    payload: Mapped[dict] = mapped_column(JSON)
    # Optional label of who/what generated it (no user model yet).
    generated_by: Mapped[str | None] = mapped_column(String(200))
    generated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
