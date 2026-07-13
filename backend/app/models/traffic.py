from datetime import date

from sqlalchemy import (
    Boolean,
    CheckConstraint,
    Date,
    Float,
    ForeignKey,
    Index,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base

# Every data row must say where it came from: a manual upload or a sync job
# (future Google OAuth integrations). Enforced with a CHECK so neither path can
# silently create orphan data.
PROVENANCE_SQL = "upload_id IS NOT NULL OR sync_job_id IS NOT NULL"


class GA4SessionsDaily(Base):
    __tablename__ = "ga4_sessions_daily"
    __table_args__ = (
        Index("ix_ga4_property_date", "property_id", "date"),
        Index("ix_ga4_ai_date", "is_ai_referral", "date"),
        CheckConstraint(PROVENANCE_SQL, name="ck_ga4_sessions_daily_provenance"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    property_id: Mapped[int] = mapped_column(ForeignKey("properties.id"))
    upload_id: Mapped[int | None] = mapped_column(ForeignKey("uploads.id"))
    sync_job_id: Mapped[int | None] = mapped_column(ForeignKey("sync_jobs.id"))
    # Line number in the source file; the row-level identifier for citations.
    source_line: Mapped[int | None] = mapped_column(Integer)
    date: Mapped[date] = mapped_column(Date)
    session_source: Mapped[str] = mapped_column(String(300))
    session_medium: Mapped[str] = mapped_column(String(100))
    session_campaign: Mapped[str | None] = mapped_column(String(300))
    landing_page: Mapped[str | None] = mapped_column(String(1000))
    # Visitor geography from GA4's City / Region dimensions when the export
    # carries them. Approximate and often "(not set)"; stored NULL when the
    # export omits geography or GA4 could not resolve it, so the audience
    # report reads NULL as "Unknown" rather than a fabricated location.
    city: Mapped[str | None] = mapped_column(String(200))
    region: Mapped[str | None] = mapped_column(String(200))
    sessions: Mapped[int] = mapped_column(Integer)
    engaged_sessions: Mapped[int] = mapped_column(Integer, default=0)
    total_users: Mapped[int] = mapped_column(Integer, default=0)
    key_events: Mapped[int] = mapped_column(Integer, default=0)
    # Stamped by the Tier 1 classifier at ingest (Phase 3). Stored so dashboards
    # and Nora query a fact, not a runtime heuristic.
    is_ai_referral: Mapped[bool] = mapped_column(Boolean, default=False)
    ai_platform: Mapped[str | None] = mapped_column(String(50))


class GSCPerformanceDaily(Base):
    __tablename__ = "gsc_performance_daily"
    __table_args__ = (
        Index("ix_gsc_property_date", "property_id", "date"),
        CheckConstraint(PROVENANCE_SQL, name="ck_gsc_performance_daily_provenance"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    property_id: Mapped[int] = mapped_column(ForeignKey("properties.id"))
    upload_id: Mapped[int | None] = mapped_column(ForeignKey("uploads.id"))
    sync_job_id: Mapped[int | None] = mapped_column(ForeignKey("sync_jobs.id"))
    # Line number in the source file; the row-level identifier for citations.
    source_line: Mapped[int | None] = mapped_column(Integer)
    date: Mapped[date] = mapped_column(Date)
    query: Mapped[str | None] = mapped_column(String(500))
    page: Mapped[str | None] = mapped_column(String(1000))
    clicks: Mapped[int] = mapped_column(Integer)
    impressions: Mapped[int] = mapped_column(Integer)
    ctr: Mapped[float] = mapped_column(Float)
    position: Mapped[float] = mapped_column(Float)


class GBPMetricsDaily(Base):
    __tablename__ = "gbp_metrics_daily"
    __table_args__ = (
        UniqueConstraint("property_id", "date", name="uq_gbp_property_date"),
        CheckConstraint(PROVENANCE_SQL, name="ck_gbp_metrics_daily_provenance"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    property_id: Mapped[int] = mapped_column(ForeignKey("properties.id"))
    upload_id: Mapped[int | None] = mapped_column(ForeignKey("uploads.id"))
    sync_job_id: Mapped[int | None] = mapped_column(ForeignKey("sync_jobs.id"))
    # Line number in the source file; the row-level identifier for citations.
    source_line: Mapped[int | None] = mapped_column(Integer)
    date: Mapped[date] = mapped_column(Date)
    search_impressions: Mapped[int] = mapped_column(Integer, default=0)
    maps_impressions: Mapped[int] = mapped_column(Integer, default=0)
    website_clicks: Mapped[int] = mapped_column(Integer, default=0)
    calls: Mapped[int] = mapped_column(Integer, default=0)
    direction_requests: Mapped[int] = mapped_column(Integer, default=0)


class PaidMediaDaily(Base):
    __tablename__ = "paid_media_daily"
    __table_args__ = (
        Index("ix_paid_property_date", "property_id", "date"),
        CheckConstraint(PROVENANCE_SQL, name="ck_paid_media_daily_provenance"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    property_id: Mapped[int] = mapped_column(ForeignKey("properties.id"))
    upload_id: Mapped[int | None] = mapped_column(ForeignKey("uploads.id"))
    sync_job_id: Mapped[int | None] = mapped_column(ForeignKey("sync_jobs.id"))
    # Line number in the source file; the row-level identifier for citations.
    source_line: Mapped[int | None] = mapped_column(Integer)
    date: Mapped[date] = mapped_column(Date)
    platform: Mapped[str] = mapped_column(String(50))
    campaign_name: Mapped[str] = mapped_column(String(300))
    impressions: Mapped[int] = mapped_column(Integer, default=0)
    clicks: Mapped[int] = mapped_column(Integer, default=0)
    spend: Mapped[float] = mapped_column(Numeric(12, 2), default=0)
    conversions: Mapped[float] = mapped_column(Float, default=0)
