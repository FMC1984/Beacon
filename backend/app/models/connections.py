"""Google account connections and sync jobs.

Schema lands ahead of any OAuth build so future API integrations (GA4 Data API,
GSC API, GBP APIs, Google Ads API) need no rewrites. Per CLAUDE.md, no OAuth
code is built until the manual CSV dashboards work and Tina explicitly says go.
"""

import enum
from datetime import date, datetime

from sqlalchemy import Date, DateTime, Enum, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models.uploads import SourceType, str_enum


class OAuthStatus(str, enum.Enum):
    DISCONNECTED = "disconnected"
    CONNECTED = "connected"
    EXPIRED = "expired"
    REVOKED = "revoked"
    ERROR = "error"


class SyncFrequency(str, enum.Enum):
    MANUAL = "manual"
    HOURLY = "hourly"
    DAILY = "daily"
    WEEKLY = "weekly"


class SyncStatus(str, enum.Enum):
    IDLE = "idle"
    SYNCING = "syncing"
    ERROR = "error"
    DISABLED = "disabled"


class SyncJobStatus(str, enum.Enum):
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class DataConnection(Base):
    __tablename__ = "data_connections"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_type: Mapped[SourceType] = mapped_column(
        str_enum(SourceType, "source_type")
    )
    account_name: Mapped[str] = mapped_column(String(300))
    external_account_id: Mapped[str] = mapped_column(String(200))
    oauth_status: Mapped[OAuthStatus] = mapped_column(
        str_enum(OAuthStatus, "oauth_status"), default=OAuthStatus.DISCONNECTED
    )
    last_sync_at: Mapped[datetime | None] = mapped_column(DateTime)
    sync_frequency: Mapped[SyncFrequency] = mapped_column(
        str_enum(SyncFrequency, "sync_frequency"), default=SyncFrequency.MANUAL
    )
    sync_status: Mapped[SyncStatus] = mapped_column(
        str_enum(SyncStatus, "sync_status"), default=SyncStatus.IDLE
    )
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now()
    )


class SyncJob(Base):
    __tablename__ = "sync_jobs"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    connection_id: Mapped[int] = mapped_column(ForeignKey("data_connections.id"))
    source_type: Mapped[SourceType] = mapped_column(
        str_enum(SourceType, "source_type")
    )
    # RAG-readiness provenance: what was pulled, from where, covering what range,
    # so synced rows are citable the way uploaded rows cite their file.
    report_type: Mapped[str | None] = mapped_column(String(200))
    endpoint: Mapped[str | None] = mapped_column(String(500))
    date_start: Mapped[date | None] = mapped_column(Date)
    date_end: Mapped[date | None] = mapped_column(Date)
    started_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now()
    )
    completed_at: Mapped[datetime | None] = mapped_column(DateTime)
    status: Mapped[SyncJobStatus] = mapped_column(
        str_enum(SyncJobStatus, "sync_job_status"), default=SyncJobStatus.RUNNING
    )
    rows_imported: Mapped[int] = mapped_column(Integer, default=0)
    rows_updated: Mapped[int] = mapped_column(Integer, default=0)
    error_message: Mapped[str | None] = mapped_column(Text)
