"""Standing AI Visibility prompts and score history.

Standing prompts are a reusable question set run on a schedule (weekly), so a
property accumulates enough queries to clear the sample-size gate and produce a
real trend instead of a one-off snapshot. Each scheduled run appends a score
history row, so AI visibility becomes a line over time, not a single number.
"""

from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class AIVisibilityPrompt(Base):
    __tablename__ = "ai_visibility_prompts"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    property_id: Mapped[int] = mapped_column(ForeignKey("properties.id"))
    platform: Mapped[str] = mapped_column(String(50), default="chatgpt")
    prompt_text: Mapped[str] = mapped_column(Text)
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class AIVisibilityScoreHistory(Base):
    __tablename__ = "ai_visibility_score_history"
    __table_args__ = (
        Index("ix_ai_vis_score_property_captured", "property_id", "captured_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    property_id: Mapped[int] = mapped_column(ForeignKey("properties.id"))
    captured_at: Mapped[datetime] = mapped_column(DateTime)
    # Null when the sample was still below the minimum at capture time (honest:
    # a point that says "not enough data yet" rather than a fake score).
    score: Mapped[float | None] = mapped_column(Float)
    sample_size: Mapped[int] = mapped_column(Integer, default=0)
    mention_rate: Mapped[float | None] = mapped_column(Float)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
