"""AI Topics (Phase 18 Share of Voice).

A topic groups AI Visibility prompts by subject (e.g. "Amenities", "Pricing",
"Location"), operator-asserted like Competitors and Property Context - Beacon
never infers a topic taxonomy. Topics are the unit Share of Voice reporting
drills into: overall SoV can hide topic-level weakness, so every prompt that
should roll up into topic-level SoV needs a topic assignment.
"""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class AITopic(Base):
    __tablename__ = "ai_topics"
    __table_args__ = (
        Index("uq_ai_topic_name", "property_id", "topic_name", unique=True),
        Index("ix_ai_topic_property", "property_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    property_id: Mapped[int] = mapped_column(ForeignKey("properties.id"))
    topic_name: Mapped[str] = mapped_column(String(200))
    description: Mapped[str | None] = mapped_column(Text)
    # Operator-asserted, drives Opportunity Engine Protect/Low Priority
    # buckets. Never derived from prompt-volume or demand data.
    priority: Mapped[str] = mapped_column(String(20), default="medium")
    status: Mapped[str] = mapped_column(String(20), default="active")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime | None] = mapped_column(DateTime)
