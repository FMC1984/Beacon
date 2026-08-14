"""Share of Voice historical snapshots (Phase 18).

Deliberately separate from AIVisibilityScoreHistory (which is overall-score-
only and owned by ai_visibility/schedule.py's snapshot_score()). This table
is topic/platform-scoped so trend, winners/losers, and competitive-rank
history can be read back without re-deriving them from raw Mention rows on
every request.

A null topic_id or platform means "all topics" / "all platforms" for that
row - snapshot_sov() writes one row per (topic x platform) combination plus
an all-topics/all-platforms rollup row per period.

The unique index below cannot itself deduplicate that all-null rollup row
(standard SQL: NULL never equals NULL, so a unique index does not constrain
across two NULLs); idempotency for repeated same-day calls is instead
guaranteed procedurally by snapshot_sov()'s delete-then-insert.
"""

from datetime import date, datetime

from sqlalchemy import (
    Boolean,
    Date,
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


class AIShareOfVoiceSnapshot(Base):
    __tablename__ = "ai_sov_snapshots"
    __table_args__ = (
        Index(
            "uq_sov_snapshot",
            "property_id", "topic_id", "platform", "period_start", "period_end",
            unique=True,
        ),
        Index("ix_sov_snapshot_property_captured", "property_id", "captured_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    property_id: Mapped[int] = mapped_column(ForeignKey("properties.id"))
    topic_id: Mapped[int | None] = mapped_column(ForeignKey("ai_topics.id"))
    platform: Mapped[str | None] = mapped_column(String(50))
    period_start: Mapped[date] = mapped_column(Date)
    period_end: Mapped[date] = mapped_column(Date)
    captured_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    property_mentions: Mapped[int] = mapped_column(Integer, default=0)
    competitor_mentions: Mapped[int] = mapped_column(Integer, default=0)
    sample_size: Mapped[int] = mapped_column(Integer, default=0)
    # Whether sample_size cleared the minimum gate at capture time.
    sufficient: Mapped[bool] = mapped_column(Boolean, default=False)
    # Null when insufficient - never a fabricated share.
    share_of_voice: Mapped[float | None] = mapped_column(Float)
    rank: Mapped[int | None] = mapped_column(Integer)
    rank_of: Mapped[int | None] = mapped_column(Integer)
