"""Durable background jobs (Phase 19, slice 1b).

A generic, leased job queue that replaces ad hoc sleep loops for Observatory
work: every unit of work is a row with an idempotency key (enqueue twice,
run once), a priority, a lease (a crashed worker's job is reclaimed when
the lease expires), an attempt counter with backoff, and a dead state after
max_attempts. Designed so the same runner can be driven from the in-process
startup loop today and from a separate worker process later without a
schema change. Pattern copied from RagSyncJob (status + counters +
error_message + timestamps), not reused: RagSyncJob is a scoped
invalidation queue with no payload, lease or attempts.
"""

from datetime import datetime

from sqlalchemy import JSON, DateTime, Index, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base

JOB_QUEUED = "queued"
JOB_LEASED = "leased"
JOB_RUNNING = "running"
JOB_COMPLETED = "completed"
JOB_FAILED = "failed"
JOB_DEAD = "dead"
JOB_CANCELLED = "cancelled"


class Job(Base):
    __tablename__ = "jobs"
    __table_args__ = (
        Index("ix_jobs_status_run_after_priority", "status", "run_after", "priority"),
        Index("ix_jobs_type_status", "job_type", "status"),
        Index("ix_jobs_org_created", "organization_id", "created_at"),
        Index("ix_jobs_lease", "lease_owner"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    job_type: Mapped[str] = mapped_column(String(60))
    idempotency_key: Mapped[str] = mapped_column(String(255), unique=True)
    payload: Mapped[dict | None] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(20), default=JOB_QUEUED)
    priority: Mapped[int] = mapped_column(Integer, default=0)
    run_after: Mapped[datetime] = mapped_column(DateTime)
    attempts: Mapped[int] = mapped_column(Integer, default=0)
    max_attempts: Mapped[int] = mapped_column(Integer, default=5)
    lease_owner: Mapped[str | None] = mapped_column(String(100))
    lease_expires_at: Mapped[datetime | None] = mapped_column(DateTime)
    last_error: Mapped[str | None] = mapped_column(Text)
    error_class: Mapped[str | None] = mapped_column(String(100))
    result: Mapped[dict | None] = mapped_column(JSON)
    organization_id: Mapped[int | None] = mapped_column(Integer)
    market_id: Mapped[int | None] = mapped_column(Integer)
    property_id: Mapped[int | None] = mapped_column(Integer)
    parent_job_id: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    started_at: Mapped[datetime | None] = mapped_column(DateTime)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime)
