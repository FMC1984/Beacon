"""Resident review storage.

Reviews are manually entered / imported for now (no scraping, no Google Business
Profile connector yet). They flow into RAG per-review for citation fidelity, and
a derived Review Intelligence chunk summarizes them.

Rating supports half-stars (Float, nullable). Distribution buckets round to the
nearest whole star with round-half-up (math.floor(rating + 0.5)); null ratings
go in a separate "no rating" bucket. See the review analyzer for the rule.

Duplicate protection: a partial unique index on (property_id, provider,
external_review_id) applies ONLY when external_review_id IS NOT NULL, so any
number of manually entered reviews (null external id) coexist without colliding.
The partial-index form works on both SQLite (tests) and Postgres (prod).
"""

from datetime import date, datetime

from sqlalchemy import (
    Date,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
    text,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class PropertyReview(Base):
    __tablename__ = "property_reviews"
    __table_args__ = (
        Index(
            "uq_review_external",
            "property_id",
            "provider",
            "external_review_id",
            unique=True,
            sqlite_where=text("external_review_id IS NOT NULL"),
            postgresql_where=text("external_review_id IS NOT NULL"),
        ),
        Index("ix_review_property_date", "property_id", "review_date"),
        Index("ix_review_property_provider", "property_id", "provider"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    property_id: Mapped[int] = mapped_column(ForeignKey("properties.id"))
    provider: Mapped[str] = mapped_column(String(50))
    external_review_id: Mapped[str | None] = mapped_column(String(200))
    author_name: Mapped[str | None] = mapped_column(String(200))
    rating: Mapped[float | None] = mapped_column(Float)
    title: Mapped[str | None] = mapped_column(String(500))
    body: Mapped[str] = mapped_column(Text)
    review_date: Mapped[date | None] = mapped_column(Date)
    response_text: Mapped[str | None] = mapped_column(Text)
    response_date: Mapped[date | None] = mapped_column(Date)
    source_url: Mapped[str | None] = mapped_column(String(1000))
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now()
    )
    updated_at: Mapped[datetime | None] = mapped_column(DateTime)
