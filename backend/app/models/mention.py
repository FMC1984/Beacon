"""Individual mention records (Phase 18 Share of Voice).

Each row is one entity (the property or one competitor) detected in one
stored AI response. This is the evidentiary leaf of the Share of Voice
drilldown: every aggregate SoV number is a count over these rows, never a
live regex re-scan, so a KPI card figure can always be reconciled down to the
exact mentions that produced it.

`raw_matched_text` is deliberately kept distinct from `normalized_name` - it
is the specific alias/name variant actually found in the response text, so
the evidence drawer can say *why* a mention was attributed to an entity
("matched via alias 'Collective on 13th'") instead of just asserting it.
"""

from datetime import datetime

from sqlalchemy import DateTime, Float, ForeignKey, Index, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base

ENTITY_PROPERTY = "property"
ENTITY_COMPETITOR = "competitor"


class Mention(Base):
    __tablename__ = "mentions"
    __table_args__ = (
        Index("ix_mention_response", "response_id"),
        Index("ix_mention_entity", "entity_type", "entity_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    response_id: Mapped[int] = mapped_column(ForeignKey("ai_visibility_queries.id"))
    # "property" | "competitor"; entity_id is Property.id or Competitor.id
    # respectively (no shared FK target, so no DB-level FK on entity_id).
    entity_type: Mapped[str] = mapped_column(String(20))
    entity_id: Mapped[int] = mapped_column(Integer)
    # Canonical name the mention rolls up to (Property.name or Competitor.name).
    normalized_name: Mapped[str] = mapped_column(String(200))
    # The literal text actually matched (may be an alias, not the canonical name).
    raw_matched_text: Mapped[str] = mapped_column(String(200))
    match_count: Mapped[int] = mapped_column(Integer, default=1)
    # Character offset of the first match in raw_response_text; evidence only.
    position: Mapped[int | None] = mapped_column(Integer)
    # 1.0 today: detection is deterministic exact literal matching, no fuzzy
    # scoring exists yet. The column exists so a future confidence model does
    # not require a migration.
    confidence: Mapped[float] = mapped_column(Float, default=1.0)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
