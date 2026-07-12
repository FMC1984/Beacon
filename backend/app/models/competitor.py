"""Operator-asserted competitor set (Phase 13 Competitor Intelligence).

Competitors are ALWAYS named by the operator, never discovered, inferred, or
scraped by Beacon - the same operator-asserted posture as Property Context. Each
row is a competitor Beacon should watch for when computing AI-answer share of
voice for a property. `aliases` lets the operator list alternate names the AI
might use (deterministic literal matching, like brand detection)."""

from datetime import datetime

from sqlalchemy import (
    JSON,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class Competitor(Base):
    __tablename__ = "competitors"
    __table_args__ = (
        Index("uq_competitor_name", "property_id", "name", unique=True),
        Index("ix_competitor_property", "property_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    property_id: Mapped[int] = mapped_column(ForeignKey("properties.id"))
    name: Mapped[str] = mapped_column(String(200))
    # Alternate names the AI might use; matched literally alongside `name`.
    aliases: Mapped[list | None] = mapped_column(JSON)
    domain: Mapped[str | None] = mapped_column(String(1000))
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now()
    )
    updated_at: Mapped[datetime | None] = mapped_column(DateTime)
