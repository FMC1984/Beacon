"""RAG synchronization queue.

Distinct from `sync_jobs` (which tracks pulling data IN from external sources,
e.g. future Google OAuth): a RagSyncJob tracks propagating already-ingested
data INTO the vector store. Imports enqueue one of these instead of embedding
inline, so the UI never waits on embedding work.
"""

import enum
from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models.uploads import str_enum


class RagSyncStatus(str, enum.Enum):
    QUEUED = "queued"
    RUNNING = "running"
    COMPLETED = "completed"
    FAILED = "failed"


class RagSyncJob(Base):
    __tablename__ = "rag_sync_jobs"
    __table_args__ = (Index("ix_rag_sync_jobs_status", "status", "id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    # Scope of the change. Null property_id + null source = full rebuild.
    property_id: Mapped[int | None] = mapped_column(ForeignKey("properties.id"))
    source: Mapped[str | None] = mapped_column(String(50))
    reason: Mapped[str] = mapped_column(String(200))
    status: Mapped[RagSyncStatus] = mapped_column(
        str_enum(RagSyncStatus, "rag_sync_status"), default=RagSyncStatus.QUEUED
    )
    chunks_total: Mapped[int] = mapped_column(Integer, default=0)
    chunks_embedded: Mapped[int] = mapped_column(Integer, default=0)
    chunks_unchanged: Mapped[int] = mapped_column(Integer, default=0)
    chunks_removed: Mapped[int] = mapped_column(Integer, default=0)
    error_message: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now()
    )
    started_at: Mapped[datetime | None] = mapped_column(DateTime)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime)
