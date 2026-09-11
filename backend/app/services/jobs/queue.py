"""Enqueue jobs (Phase 19)."""

from datetime import datetime, timezone

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from app.models import Job
from app.models.jobs import JOB_QUEUED


def utcnow() -> datetime:
    """Naive UTC, matching how SQLite hands datetimes back."""
    return datetime.now(timezone.utc).replace(tzinfo=None)


def enqueue(
    db: Session,
    job_type: str,
    payload: dict | None = None,
    *,
    idempotency_key: str,
    priority: int = 0,
    run_after: datetime | None = None,
    max_attempts: int = 5,
    organization_id: int | None = None,
    market_id: int | None = None,
    property_id: int | None = None,
    parent_job_id: int | None = None,
    now: datetime | None = None,
) -> tuple[Job, bool]:
    """(job, created). A second enqueue with the same idempotency_key returns
    the existing row untouched, whatever its status - the caller decides
    whether a completed job should be re-queued via `requeue`."""
    existing = db.query(Job).filter_by(idempotency_key=idempotency_key).one_or_none()
    if existing is not None:
        return existing, False
    now = now or utcnow()
    job = Job(
        job_type=job_type,
        idempotency_key=idempotency_key,
        payload=payload,
        status=JOB_QUEUED,
        priority=priority,
        run_after=run_after or now,
        attempts=0,
        max_attempts=max_attempts,
        organization_id=organization_id,
        market_id=market_id,
        property_id=property_id,
        parent_job_id=parent_job_id,
    )
    db.add(job)
    try:
        db.commit()
    except IntegrityError:
        db.rollback()
        return db.query(Job).filter_by(idempotency_key=idempotency_key).one(), False
    db.refresh(job)
    return job, True


def requeue(db: Session, job: Job, now: datetime | None = None) -> Job:
    """Put a completed/failed/dead job back on the queue (operator retry)."""
    job.status = JOB_QUEUED
    job.run_after = now or utcnow()
    job.lease_owner = None
    job.lease_expires_at = None
    job.last_error = None
    job.error_class = None
    job.completed_at = None
    db.commit()
    return job
