"""Standing AI Visibility prompts and score history.

Standing prompts are a reusable question set run on a schedule (weekly), so a
property accumulates enough queries to clear the sample-size gate and produce a
real trend instead of a one-off snapshot. Each scheduled run appends a score
history row, so AI visibility becomes a line over time, not a single number.
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
    # Question-set metadata (operator-asserted, imported from a seed JSON).
    # cadence: "weekly" | "monthly". runs_per_cycle: how many runs per cycle
    # (weeklies run once per week; monthlies typically twice per month).
    cadence: Mapped[str] = mapped_column(String(20), default="weekly")
    runs_per_cycle: Mapped[int] = mapped_column(Integer, default=1)
    intent: Mapped[str | None] = mapped_column(String(50))
    # Real topic grouping for Share of Voice by-topic reporting (Phase 18) -
    # distinct from `intent`, which stays a free-text classification tag.
    topic_id: Mapped[int | None] = mapped_column(ForeignKey("ai_topics.id"))
    # Free-text SoV filter dimensions (Phase 18), same posture as `intent`:
    # operator types whatever they want, no controlled vocabulary yet.
    audience: Mapped[str | None] = mapped_column(String(100))
    persona: Mapped[str | None] = mapped_column(String(100))
    location_market: Mapped[str | None] = mapped_column(String(100))
    priority: Mapped[str | None] = mapped_column(String(20))
    tags: Mapped[list | None] = mapped_column(JSON)
    # The page that should own this answer, relative to the property site.
    owning_url: Mapped[str | None] = mapped_column(String(500))
    # Volatile answers (waitlist status, schedules) go stale; flagged so a
    # miss on a volatile question reads as urgent.
    volatile: Mapped[bool] = mapped_column(Boolean, default=False)
    # Strings a correct answer must contain (deterministic containment check,
    # evaluated at read time against stored responses - never an LLM judge).
    must_contain: Mapped[list | None] = mapped_column(JSON)
    notes: Mapped[str | None] = mapped_column(Text)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime)
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
