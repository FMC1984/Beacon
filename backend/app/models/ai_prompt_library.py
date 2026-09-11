"""Prompt library structures (Phase 19, slice 2).

- AIPromptCluster: wording variants of the same question grouped by meaning
  (embeddings + topic/intent bucketing). Routine monitoring runs one
  representative per cluster and rotates variants, so a market's prompt
  universe costs one run per cluster, not one per wording.
- AIPromptEmbedding: the vector for a prompt (packed float32), keyed by the
  prompt text hash so re-clustering never re-embeds unchanged text.
- AIPromptAssignment: which properties (or whole markets) a prompt/cluster
  is monitored for - the subscription that lets ONE market observation be
  scored against MANY properties in Phase 3.
"""

from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Index,
    Integer,
    LargeBinary,
    String,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base

PROMPT_SCOPE_MARKET = "market"
PROMPT_SCOPE_FEATURE = "feature"
PROMPT_SCOPE_BRAND = "brand"
PROMPT_SCOPE_SENTINEL = "sentinel"
PROMPT_SCOPES = (PROMPT_SCOPE_MARKET, PROMPT_SCOPE_FEATURE, PROMPT_SCOPE_BRAND, PROMPT_SCOPE_SENTINEL)


class AIPromptCluster(Base):
    __tablename__ = "ai_prompt_clusters"
    __table_args__ = (
        Index("ix_ai_prompt_clusters_market_topic", "market_id", "topic_key"),
        Index("ix_ai_prompt_clusters_property", "property_id"),
        Index("ix_ai_prompt_clusters_org_scope", "organization_id", "scope"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organization_id: Mapped[int | None] = mapped_column(Integer)
    market_id: Mapped[int | None] = mapped_column(ForeignKey("markets.id"))
    property_id: Mapped[int | None] = mapped_column(ForeignKey("properties.id"))
    scope: Mapped[str] = mapped_column(String(20))
    label: Mapped[str] = mapped_column(String(300))
    topic_key: Mapped[str | None] = mapped_column(String(60))
    intent: Mapped[str | None] = mapped_column(String(50))
    geography: Mapped[str | None] = mapped_column(String(100))
    persona: Mapped[str | None] = mapped_column(String(100))
    funnel_stage: Mapped[str | None] = mapped_column(String(30))
    importance: Mapped[int] = mapped_column(Integer, default=3)
    representative_prompt_id: Mapped[int | None] = mapped_column(Integer)
    variant_count: Mapped[int] = mapped_column(Integer, default=1)
    centroid: Mapped[bytes | None] = mapped_column(LargeBinary)
    embedding_model: Mapped[str | None] = mapped_column(String(100))
    clustering_version: Mapped[int] = mapped_column(Integer, default=1)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime | None] = mapped_column(DateTime)


class AIPromptEmbedding(Base):
    __tablename__ = "ai_prompt_embeddings"

    prompt_id: Mapped[int] = mapped_column(
        ForeignKey("ai_visibility_prompts.id"), primary_key=True
    )
    model: Mapped[str] = mapped_column(String(100))
    dim: Mapped[int] = mapped_column(Integer)
    vector: Mapped[bytes] = mapped_column(LargeBinary)
    prompt_hash: Mapped[str] = mapped_column(String(64))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class AIPromptAssignment(Base):
    __tablename__ = "ai_prompt_assignments"
    __table_args__ = (
        Index("ix_ai_prompt_assignments_property", "property_id", "active"),
        Index("ix_ai_prompt_assignments_market", "market_id", "active"),
        Index("ix_ai_prompt_assignments_cluster", "cluster_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organization_id: Mapped[int | None] = mapped_column(Integer)
    prompt_id: Mapped[int | None] = mapped_column(ForeignKey("ai_visibility_prompts.id"))
    cluster_id: Mapped[int | None] = mapped_column(ForeignKey("ai_prompt_clusters.id"))
    property_id: Mapped[int | None] = mapped_column(ForeignKey("properties.id"))
    market_id: Mapped[int | None] = mapped_column(ForeignKey("markets.id"))
    assignment_key: Mapped[str] = mapped_column(String(120), unique=True)
    tier: Mapped[str] = mapped_column(String(30), default="standard_property")
    active: Mapped[bool] = mapped_column(Boolean, default=True)
    source: Mapped[str] = mapped_column(String(20), default="auto")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
