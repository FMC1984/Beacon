"""Lease-based job runner (Phase 19).

claim_next() is a single conditional UPDATE: the row is leased only if it
is still queued at the moment of the update, so two workers can never take
the same job (rowcount decides). Works on SQLite and Postgres (correlated
scalar subquery; Postgres can later add SKIP LOCKED). A handler exception
re-queues the job with exponential backoff until max_attempts, then parks
it as dead. Expired leases (a crashed worker) are reclaimed on every drain.
"""

import os
import random
from datetime import datetime, timedelta
from uuid import uuid4

from sqlalchemy import func, select, update
from sqlalchemy.orm import Session

from app.config import settings
from app.models import AppState, Job
from app.models.jobs import (
    JOB_COMPLETED,
    JOB_DEAD,
    JOB_LEASED,
    JOB_QUEUED,
    JOB_RUNNING,
)
from app.services.jobs.handlers import HANDLERS
from app.services.jobs.queue import utcnow
from app.services.observatory.observability import log_event

BACKOFF_BASE_SECONDS = 30
BACKOFF_MAX_SECONDS = 3600
HEARTBEAT_KEY = "jobs_runner"


def backoff(attempts: int, jitter: bool = True) -> float:
    base = min(BACKOFF_BASE_SECONDS * (2 ** max(0, attempts)), BACKOFF_MAX_SECONDS)
    return base + (random.uniform(0, 5) if jitter else 0.0)


def claim_next(
    db: Session,
    worker_id: str,
    job_types: list[str] | None = None,
    now: datetime | None = None,
    lease_seconds: int | None = None,
) -> Job | None:
    now = now or utcnow()
    token = f"{worker_id}:{uuid4().hex[:10]}"
    expires = now + timedelta(seconds=lease_seconds or settings.jobs_lease_seconds)

    candidate = select(Job.id).where(Job.status == JOB_QUEUED, Job.run_after <= now)
    if job_types:
        candidate = candidate.where(Job.job_type.in_(job_types))
    candidate = (
        candidate.order_by(Job.priority.desc(), Job.id.asc()).limit(1).scalar_subquery()
    )
    stmt = (
        update(Job)
        .where(Job.id == candidate, Job.status == JOB_QUEUED)
        .values(
            status=JOB_LEASED,
            lease_owner=token,
            lease_expires_at=expires,
            attempts=Job.attempts + 1,
            started_at=func.coalesce(Job.started_at, now),
        )
        .execution_options(synchronize_session=False)
    )
    result = db.execute(stmt)
    db.commit()
    if result.rowcount != 1:
        return None
    # populate_existing: the row may already sit in this session's identity
    # map with pre-lease attributes (expire_on_commit is off app-wide).
    return (
        db.query(Job)
        .filter_by(lease_owner=token, status=JOB_LEASED)
        .populate_existing()
        .one()
    )


def run_one(db: Session, job: Job, now: datetime | None = None, jitter: bool = True) -> Job:
    now = now or utcnow()
    job.status = JOB_RUNNING
    db.commit()
    job_id = job.id
    try:
        handler = HANDLERS.get(job.job_type)
        if handler is None:
            raise KeyError(f"No handler registered for job_type '{job.job_type}'.")
        result = handler(db, job)
        job = db.get(Job, job_id)
        job.status = JOB_COMPLETED
        job.result = result if isinstance(result, dict) else {"result": result}
        job.completed_at = now
        job.lease_owner = None
        job.lease_expires_at = None
        job.last_error = None
        job.error_class = None
        db.commit()
        log_event(
            "job.completed", job_id=job.id, job_type=job.job_type,
            attempts=job.attempts, organization_id=job.organization_id,
            property_id=job.property_id, market_id=job.market_id,
        )
    except Exception as exc:
        db.rollback()
        job = db.get(Job, job_id)
        job.last_error = str(exc)[:2000]
        job.error_class = type(exc).__name__
        job.lease_owner = None
        job.lease_expires_at = None
        if job.attempts >= job.max_attempts:
            job.status = JOB_DEAD
            job.completed_at = now
        else:
            job.status = JOB_QUEUED
            job.run_after = now + timedelta(seconds=backoff(job.attempts, jitter=jitter))
        db.commit()
        log_event(
            "job.failed", job_id=job.id, job_type=job.job_type, attempts=job.attempts,
            status=job.status, error_class=job.error_class, retry_count=job.attempts - 1,
        )
    return job


def reclaim_expired(db: Session, now: datetime | None = None) -> int:
    now = now or utcnow()
    expired = (
        db.query(Job)
        .filter(Job.status.in_([JOB_LEASED, JOB_RUNNING]), Job.lease_expires_at < now)
        .populate_existing()
        .all()
    )
    for job in expired:
        job.lease_owner = None
        job.lease_expires_at = None
        job.last_error = "lease expired (worker did not finish)"
        job.error_class = "LeaseExpired"
        if job.attempts >= job.max_attempts:
            job.status = JOB_DEAD
            job.completed_at = now
        else:
            job.status = JOB_QUEUED
            job.run_after = now
    if expired:
        db.commit()
    return len(expired)


def drain(
    db: Session,
    worker_id: str = "inproc",
    limit: int | None = None,
    job_types: list[str] | None = None,
    now: datetime | None = None,
    jitter: bool = True,
) -> dict:
    limit = limit or settings.jobs_batch_limit
    counts = {"reclaimed": reclaim_expired(db, now), "claimed": 0, "completed": 0, "requeued": 0, "dead": 0}
    for _ in range(limit):
        job = claim_next(db, worker_id, job_types=job_types, now=now)
        if job is None:
            break
        counts["claimed"] += 1
        job = run_one(db, job, now=now, jitter=jitter)
        if job.status == JOB_COMPLETED:
            counts["completed"] += 1
        elif job.status == JOB_DEAD:
            counts["dead"] += 1
        else:
            counts["requeued"] += 1
    return counts


def heartbeat(db: Session, counts: dict, now: datetime | None = None) -> None:
    now = now or utcnow()
    row = db.get(AppState, HEARTBEAT_KEY)
    value = {"last_tick": now.isoformat(), **counts}
    if row is None:
        db.add(AppState(key=HEARTBEAT_KEY, value=value))
    else:
        row.value = value
    db.commit()


def drain_once(worker_id: str | None = None) -> dict:
    """One tick for the in-process loop and the CLI: own session, heartbeat."""
    from app.db import SessionLocal

    worker_id = worker_id or f"inproc-{os.getpid()}"
    db = SessionLocal()
    try:
        counts = drain(db, worker_id=worker_id)
        heartbeat(db, counts)
        return counts
    finally:
        db.close()
