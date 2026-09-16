"""Observatory scale rollups (Phase 19).

Source influence, run cost and competitor standing are all computed live
today by scanning ai_citations, ai_runs and ai_property_observations. That is
correct and stays the source of truth; these tables are a cache so the same
answers keep arriving quickly as a portfolio grows from one property to
thousands.

Every row is rebuilt delete-then-insert per rollup_key from the same code
path the live readers use, and a reconciliation test asserts the cached
numbers equal the live ones. A cache that can silently drift from the truth
would be worse than no cache at all.
"""

from datetime import date, datetime

from sqlalchemy import Date, DateTime, Float, Index, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base

ROLLUP_VERSION = 1
# A period is either a calendar day ("2026-09-16") or a trailing window
# ("30d"); the key carries which, so the two never mix in one query.
PERIOD_DAY = "day"
PERIOD_WINDOW = "window"


class AISourceDomainRollup(Base):
    """Citations per domain for one scope and period: what the Sources tab
    reads instead of scanning every citation in the window."""

    __tablename__ = "ai_source_domains"
    __table_args__ = (
        Index("uq_ai_source_domains_key", "rollup_key", unique=True),
        Index("ix_ai_source_domains_scope", "property_id", "period", "citations"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organization_id: Mapped[int | None] = mapped_column(Integer)
    property_id: Mapped[int | None] = mapped_column(Integer)
    market_id: Mapped[int | None] = mapped_column(Integer)
    period: Mapped[str] = mapped_column(String(20))
    period_kind: Mapped[str] = mapped_column(String(10), default=PERIOD_WINDOW)
    window_start: Mapped[date] = mapped_column(Date)
    window_end: Mapped[date] = mapped_column(Date)
    domain: Mapped[str] = mapped_column(String(255))
    # Relative to the property this row is scoped to: owned, competitor,
    # property_site (another scored property's site), directory, other.
    source_type: Mapped[str | None] = mapped_column(String(40))
    citations: Mapped[int] = mapped_column(Integer, default=0)
    responses: Mapped[int] = mapped_column(Integer, default=0)
    share: Mapped[float | None] = mapped_column(Float)
    rollup_version: Mapped[int] = mapped_column(Integer, default=ROLLUP_VERSION)
    rollup_key: Mapped[str] = mapped_column(String(200))
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


class AIRunCostDaily(Base):
    """One row per organization, day, provider and model. Tokens and search
    operations are OBSERVED; estimated_usd is MODELED and stays null when no
    rate is configured, so `priced_runs` is what makes a total trustworthy."""

    __tablename__ = "ai_run_costs_daily"
    __table_args__ = (
        Index("uq_ai_run_costs_daily_key", "rollup_key", unique=True),
        Index("ix_ai_run_costs_daily_org_day", "organization_id", "day"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    day: Mapped[date] = mapped_column(Date)
    organization_id: Mapped[int | None] = mapped_column(Integer)
    provider: Mapped[str | None] = mapped_column(String(30))
    model: Mapped[str | None] = mapped_column(String(100))
    run_scope: Mapped[str | None] = mapped_column(String(20))
    runs: Mapped[int] = mapped_column(Integer, default=0)
    runs_success: Mapped[int] = mapped_column(Integer, default=0)
    runs_failed: Mapped[int] = mapped_column(Integer, default=0)
    runs_discarded: Mapped[int] = mapped_column(Integer, default=0)
    priced_runs: Mapped[int] = mapped_column(Integer, default=0)
    token_input: Mapped[int] = mapped_column(Integer, default=0)
    token_output: Mapped[int] = mapped_column(Integer, default=0)
    token_reasoning: Mapped[int] = mapped_column(Integer, default=0)
    token_cached: Mapped[int] = mapped_column(Integer, default=0)
    search_operations: Mapped[int] = mapped_column(Integer, default=0)
    estimated_usd: Mapped[float | None] = mapped_column(Float)
    observations: Mapped[int] = mapped_column(Integer, default=0)
    rollup_version: Mapped[int] = mapped_column(Integer, default=ROLLUP_VERSION)
    rollup_key: Mapped[str] = mapped_column(String(200))
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())


class AICompetitorStat(Base):
    """How one tracked competitor stood against one property over a window:
    how often they shared an answer, who was named, who was cited."""

    __tablename__ = "ai_competitor_stats"
    __table_args__ = (
        Index("uq_ai_competitor_stats_key", "rollup_key", unique=True),
        Index("ix_ai_competitor_stats_property", "property_id", "period"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organization_id: Mapped[int | None] = mapped_column(Integer)
    property_id: Mapped[int] = mapped_column(Integer)
    competitor_id: Mapped[int] = mapped_column(Integer)
    competitor_name: Mapped[str] = mapped_column(String(200))
    period: Mapped[str] = mapped_column(String(20))
    window_start: Mapped[date] = mapped_column(Date)
    window_end: Mapped[date] = mapped_column(Date)
    shared_responses: Mapped[int] = mapped_column(Integer, default=0)
    competitor_mentions: Mapped[int] = mapped_column(Integer, default=0)
    property_mentions: Mapped[int] = mapped_column(Integer, default=0)
    co_mentions: Mapped[int] = mapped_column(Integer, default=0)
    competitor_wins: Mapped[int] = mapped_column(Integer, default=0)
    property_wins: Mapped[int] = mapped_column(Integer, default=0)
    competitor_citations: Mapped[int] = mapped_column(Integer, default=0)
    property_citations: Mapped[int] = mapped_column(Integer, default=0)
    # Null below the minimum sample rather than a misleading zero.
    co_mention_rate: Mapped[float | None] = mapped_column(Float)
    competitor_win_rate: Mapped[float | None] = mapped_column(Float)
    citation_share: Mapped[float | None] = mapped_column(Float)
    rollup_version: Mapped[int] = mapped_column(Integer, default=ROLLUP_VERSION)
    rollup_key: Mapped[str] = mapped_column(String(200))
    updated_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now(), onupdate=func.now())
