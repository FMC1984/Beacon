"""Derived observations and daily rollups (Phase 19, slice 3).

AIPropertyObservation is the core of shared market scoring: ONE stored AI
response (a market run) fans out into one row per eligible property, each
saying whether that property was mentioned, cited, recommended, in what
position and with what sentiment, and how its tracked competitors fared in
the same answer - all derived in code from the Mention and AICitation rows,
never by re-running the provider. Every Observatory metric reads these
rows (through the daily rollups), so a KPI can always be walked back to
the exact response and mention that produced it.

Rollups (ai_visibility_daily, ai_cluster_visibility_daily, ai_market_daily)
are delete-then-insert per rollup_key and refreshed incrementally from a
watermark, so dashboards never scan raw observations.
"""

from datetime import date, datetime

from sqlalchemy import (
    JSON,
    Boolean,
    Date,
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

DERIVATION_VERSION = 1
METRIC_VERSION = 1
PLATFORM_ALL = "all"


class AIPropertyObservation(Base):
    __tablename__ = "ai_property_observations"
    __table_args__ = (
        Index("uq_ai_property_observations_response_property", "response_id", "property_id", unique=True),
        Index("ix_ai_property_observations_property_observed", "property_id", "observed_at"),
        Index("ix_ai_property_observations_market_observed", "market_id", "observed_at"),
        Index("ix_ai_property_observations_cluster_property", "cluster_id", "property_id", "observed_at"),
        Index("ix_ai_property_observations_org_observed", "organization_id", "observed_at"),
        Index("ix_ai_property_observations_rolled_up", "rolled_up"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organization_id: Mapped[int | None] = mapped_column(Integer)
    property_id: Mapped[int] = mapped_column(ForeignKey("properties.id"))
    response_id: Mapped[int] = mapped_column(ForeignKey("ai_visibility_queries.id"))
    run_id: Mapped[int | None] = mapped_column(ForeignKey("ai_runs.id"))
    prompt_id: Mapped[int | None] = mapped_column(Integer)
    cluster_id: Mapped[int | None] = mapped_column(Integer)
    market_id: Mapped[int | None] = mapped_column(Integer)
    platform: Mapped[str] = mapped_column(String(50))
    provider: Mapped[str | None] = mapped_column(String(30))
    observed_at: Mapped[datetime] = mapped_column(DateTime)
    eligible: Mapped[bool] = mapped_column(Boolean, default=True)
    eligibility_reason: Mapped[str | None] = mapped_column(String(60))
    mentioned: Mapped[bool] = mapped_column(Boolean, default=False)
    mention_position: Mapped[int | None] = mapped_column(Integer)
    # 1 = first entity named in the answer, among property + competitors.
    mention_rank: Mapped[int | None] = mapped_column(Integer)
    mention_confidence: Mapped[float | None] = mapped_column(Float)
    cited: Mapped[bool] = mapped_column(Boolean, default=False)
    citation_count: Mapped[int] = mapped_column(Integer, default=0)
    citation_first_order: Mapped[int | None] = mapped_column(Integer)
    matched_citation_ids: Mapped[list | None] = mapped_column(JSON)
    # MODELED (rule_v1): None when the property was not mentioned at all.
    recommended: Mapped[bool | None] = mapped_column(Boolean)
    recommendation_method: Mapped[str | None] = mapped_column(String(30))
    sentiment: Mapped[str | None] = mapped_column(String(10))
    sentiment_score: Mapped[float | None] = mapped_column(Float)
    context_excerpt: Mapped[str | None] = mapped_column(Text)
    competitor_mentioned_count: Mapped[int] = mapped_column(Integer, default=0)
    competitor_cited_count: Mapped[int] = mapped_column(Integer, default=0)
    competitor_entity_ids: Mapped[list | None] = mapped_column(JSON)
    total_citation_count: Mapped[int] = mapped_column(Integer, default=0)
    derivation_version: Mapped[int] = mapped_column(Integer, default=DERIVATION_VERSION)
    rolled_up: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class AIDiscoveredEntity(Base):
    """Names that keep showing up in market answers but are not tracked
    competitors of anyone yet (populated by discovery in a later slice)."""

    __tablename__ = "ai_discovered_entities"
    __table_args__ = (
        Index("uq_ai_discovered_entities_market_name", "market_id", "normalized_name", unique=True),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    market_id: Mapped[int | None] = mapped_column(ForeignKey("markets.id"))
    organization_id: Mapped[int | None] = mapped_column(Integer)
    normalized_name: Mapped[str] = mapped_column(String(200))
    display_name: Mapped[str] = mapped_column(String(200))
    domain: Mapped[str | None] = mapped_column(String(255))
    aliases: Mapped[list | None] = mapped_column(JSON)
    entity_kind: Mapped[str] = mapped_column(String(20), default="unknown")
    first_seen: Mapped[datetime | None] = mapped_column(DateTime)
    last_seen: Mapped[datetime | None] = mapped_column(DateTime)
    mention_count: Mapped[int] = mapped_column(Integer, default=0)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class AIVisibilityDaily(Base):
    __tablename__ = "ai_visibility_daily"
    __table_args__ = (
        Index("uq_ai_visibility_daily_key", "rollup_key", unique=True),
        Index("ix_ai_visibility_daily_property_day", "property_id", "day"),
        Index("ix_ai_visibility_daily_org_day", "organization_id", "day"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    day: Mapped[date] = mapped_column(Date)
    organization_id: Mapped[int | None] = mapped_column(Integer)
    property_id: Mapped[int] = mapped_column(Integer)
    platform: Mapped[str] = mapped_column(String(50))  # "all" or a platform key
    eligible_count: Mapped[int] = mapped_column(Integer, default=0)
    mentioned_count: Mapped[int] = mapped_column(Integer, default=0)
    cited_count: Mapped[int] = mapped_column(Integer, default=0)
    recommended_count: Mapped[int] = mapped_column(Integer, default=0)
    owned_citation_count: Mapped[int] = mapped_column(Integer, default=0)
    tracked_citation_count: Mapped[int] = mapped_column(Integer, default=0)
    total_citation_count: Mapped[int] = mapped_column(Integer, default=0)
    property_mention_responses: Mapped[int] = mapped_column(Integer, default=0)
    competitor_mention_count: Mapped[int] = mapped_column(Integer, default=0)
    competitor_win_count: Mapped[int] = mapped_column(Integer, default=0)
    sentiment_pos: Mapped[int] = mapped_column(Integer, default=0)
    sentiment_neu: Mapped[int] = mapped_column(Integer, default=0)
    sentiment_neg: Mapped[int] = mapped_column(Integer, default=0)
    runs_count: Mapped[int] = mapped_column(Integer, default=0)
    metric_version: Mapped[int] = mapped_column(Integer, default=METRIC_VERSION)
    rollup_key: Mapped[str] = mapped_column(String(120))
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


class AIClusterVisibilityDaily(Base):
    __tablename__ = "ai_cluster_visibility_daily"
    __table_args__ = (
        Index("uq_ai_cluster_visibility_daily_key", "rollup_key", unique=True),
        Index("ix_ai_cluster_visibility_daily_property_cluster_day", "property_id", "cluster_id", "day"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    day: Mapped[date] = mapped_column(Date)
    property_id: Mapped[int] = mapped_column(Integer)
    cluster_id: Mapped[int] = mapped_column(Integer)
    eligible_count: Mapped[int] = mapped_column(Integer, default=0)
    mentioned_count: Mapped[int] = mapped_column(Integer, default=0)
    cited_count: Mapped[int] = mapped_column(Integer, default=0)
    recommended_count: Mapped[int] = mapped_column(Integer, default=0)
    competitor_mention_count: Mapped[int] = mapped_column(Integer, default=0)
    competitor_win_count: Mapped[int] = mapped_column(Integer, default=0)
    metric_version: Mapped[int] = mapped_column(Integer, default=METRIC_VERSION)
    rollup_key: Mapped[str] = mapped_column(String(120))
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


class AIMarketDaily(Base):
    __tablename__ = "ai_market_daily"
    __table_args__ = (
        Index("uq_ai_market_daily_key", "rollup_key", unique=True),
        Index("ix_ai_market_daily_market_day", "market_id", "day"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    day: Mapped[date] = mapped_column(Date)
    market_id: Mapped[int] = mapped_column(Integer)
    platform: Mapped[str] = mapped_column(String(50))
    runs_count: Mapped[int] = mapped_column(Integer, default=0)
    responses_count: Mapped[int] = mapped_column(Integer, default=0)
    properties_scored: Mapped[int] = mapped_column(Integer, default=0)
    citations_count: Mapped[int] = mapped_column(Integer, default=0)
    distinct_domains: Mapped[int] = mapped_column(Integer, default=0)
    metric_version: Mapped[int] = mapped_column(Integer, default=METRIC_VERSION)
    rollup_key: Mapped[str] = mapped_column(String(120))
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())
