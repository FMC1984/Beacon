"""AI Visibility query storage (Phase 11.5 foundation).

Each row is one executed query against an external AI platform and its verbatim
response. The raw response is the evidentiary record - the same role review
text plays in Phase 11 - and is preserved permanently so every downstream claim
is citable. `platform` is a controlled vocabulary validated on assignment
against app/reference_data/ai_visibility.json (vocabulary-in-JSON, like the
Phase 10.5 property-type pattern), not a DB-native enum, so adding a platform
needs no migration.

`brand_mentioned` and `sources_cited` are DETERMINISTICALLY parsed from
`raw_response_text`; the query execution that produced that text is the only
non-deterministic step in the whole system.
"""

from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class AIVisibilityQuery(Base):
    __tablename__ = "ai_visibility_queries"
    __table_args__ = (
        Index("ix_ai_visibility_property_executed", "property_id", "executed_at"),
        Index("ix_ai_visibility_property_platform", "property_id", "platform"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    property_id: Mapped[int] = mapped_column(ForeignKey("properties.id"))
    platform: Mapped[str] = mapped_column(String(50))
    prompt_text: Mapped[str] = mapped_column(Text)
    # Verbatim external-AI response. Immutable evidence; never rewritten.
    raw_response_text: Mapped[str] = mapped_column(Text)
    executed_at: Mapped[datetime] = mapped_column(DateTime)
    # Deterministically parsed from raw_response_text.
    brand_mentioned: Mapped[bool] = mapped_column(Boolean, default=False)
    sources_cited: Mapped[list | None] = mapped_column(JSON)
    # "success" | "failed" (Phase 18 schema; only "success" rows are written
    # today - see mentions.py module docstring for the deferred-failure-
    # persistence decision).
    execution_status: Mapped[str] = mapped_column(String(20), default="success")
    error_message: Mapped[str | None] = mapped_column(Text)
    # Snapshot of the platform's {connector, live} metadata (from
    # ai_visibility.json) at execution time, so a stored row stays truthful
    # about its actual source even if the reference vocabulary changes later
    # - e.g. never silently reads as consumer "ChatGPT" if it was really an
    # API web-search call.
    model_metadata: Mapped[dict | None] = mapped_column(JSON)
    # Denormalized Mention-row counts, written by persist_mentions_for_query()
    # so Share of Voice reads never COUNT the mentions table per response.
    property_mention_count: Mapped[int] = mapped_column(Integer, default=0)
    competitor_mention_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now()
    )
    updated_at: Mapped[datetime | None] = mapped_column(DateTime)
