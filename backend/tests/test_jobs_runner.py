"""Phase 19 (1b): the durable jobs runner. Idempotent enqueue, atomic
leasing (a job can only be claimed once), priority ordering, retry with
backoff until max_attempts then dead, lease reclaim after a crash, and a
final-outcome handler contract for provider runs."""

from datetime import timedelta

import pytest

from app.models import AppState, Job, Property
from app.models.jobs import JOB_COMPLETED, JOB_DEAD, JOB_QUEUED
from app.services.jobs import handlers
from app.services.jobs.queue import enqueue, requeue, utcnow
from app.services.jobs.runner import (
    backoff,
    claim_next,
    drain,
    heartbeat,
    reclaim_expired,
    run_one,
)


@pytest.fixture()
def flaky(monkeypatch):
    """A handler that fails N times then succeeds; registered for the test."""
    state = {"calls": 0, "fail_times": 0}

    def handler(db, job):
        state["calls"] += 1
        if state["calls"] <= state["fail_times"]:
            raise RuntimeError(f"boom {state['calls']}")
        return {"calls": state["calls"]}

    monkeypatch.setitem(handlers.HANDLERS, "flaky", handler)
    return state


def test_enqueue_is_idempotent_by_key(db):
    a, created_a = enqueue(db, "noop", {"n": 1}, idempotency_key="noop:1")
    b, created_b = enqueue(db, "noop", {"n": 2}, idempotency_key="noop:1")
    assert created_a is True and created_b is False
    assert a.id == b.id and b.payload == {"n": 1}
    assert db.query(Job).count() == 1


def test_claim_is_atomic_and_orders_by_priority_then_id(db):
    enqueue(db, "noop", idempotency_key="k1", priority=0)
    high, _ = enqueue(db, "noop", idempotency_key="k2", priority=5)
    enqueue(db, "noop", idempotency_key="k3", priority=0)

    first = claim_next(db, "w1")
    assert first.id == high.id and first.status == "leased" and first.attempts == 1
    second = claim_next(db, "w2")
    third = claim_next(db, "w3")
    assert {first.id, second.id, third.id} == {1, 2, 3}
    assert claim_next(db, "w4") is None  # nothing left to claim


def test_run_after_gates_claims(db):
    later = utcnow() + timedelta(hours=1)
    enqueue(db, "noop", idempotency_key="later", run_after=later)
    assert claim_next(db, "w") is None
    assert claim_next(db, "w", now=later) is not None


def test_success_completes_with_result(db):
    job, _ = enqueue(db, "noop", {"x": 1}, idempotency_key="ok")
    job = run_one(db, claim_next(db, "w"))
    assert job.status == JOB_COMPLETED
    assert job.result == {"ok": True, "payload": {"x": 1}}
    assert job.lease_owner is None and job.completed_at is not None


def test_failure_requeues_with_backoff_then_dies(db, flaky):
    flaky["fail_times"] = 10
    job, _ = enqueue(db, "flaky", idempotency_key="f", max_attempts=3)
    now = utcnow()

    job = run_one(db, claim_next(db, "w", now=now), now=now, jitter=False)
    assert job.status == JOB_QUEUED and job.attempts == 1
    assert job.error_class == "RuntimeError" and "boom 1" in job.last_error
    assert job.run_after == now + timedelta(seconds=backoff(1, jitter=False))

    # Not claimable until the backoff has elapsed.
    assert claim_next(db, "w", now=now) is None
    t2 = job.run_after
    job = run_one(db, claim_next(db, "w", now=t2), now=t2, jitter=False)
    assert job.status == JOB_QUEUED and job.attempts == 2
    t3 = job.run_after
    job = run_one(db, claim_next(db, "w", now=t3), now=t3, jitter=False)
    assert job.status == JOB_DEAD and job.attempts == 3
    assert claim_next(db, "w", now=t3 + timedelta(days=1)) is None


def test_backoff_is_exponential_and_capped():
    assert backoff(1, jitter=False) == 60
    assert backoff(2, jitter=False) == 120
    assert backoff(10, jitter=False) == 3600


def test_flaky_handler_eventually_succeeds(db, flaky):
    flaky["fail_times"] = 1
    enqueue(db, "flaky", idempotency_key="f2")
    now = utcnow()
    job = run_one(db, claim_next(db, "w", now=now), now=now, jitter=False)
    assert job.status == JOB_QUEUED
    job = run_one(db, claim_next(db, "w", now=job.run_after), now=job.run_after)
    assert job.status == JOB_COMPLETED and job.result == {"calls": 2}


def test_unknown_job_type_dies_after_max_attempts(db):
    enqueue(db, "does_not_exist", idempotency_key="u", max_attempts=1)
    job = run_one(db, claim_next(db, "w"))
    assert job.status == JOB_DEAD and job.error_class == "KeyError"


def test_expired_lease_is_reclaimed(db):
    enqueue(db, "noop", idempotency_key="crash")
    now = utcnow()
    leased = claim_next(db, "crashed-worker", now=now, lease_seconds=60)
    assert leased.status == "leased"
    assert reclaim_expired(db, now=now + timedelta(seconds=30)) == 0
    assert reclaim_expired(db, now=now + timedelta(seconds=61)) == 1
    job = db.get(Job, leased.id)
    assert job.status == JOB_QUEUED and job.error_class == "LeaseExpired"
    assert job.attempts == 1  # the crashed attempt still counts


def test_drain_processes_batch_and_reports_counts(db, flaky):
    flaky["fail_times"] = 100
    enqueue(db, "noop", idempotency_key="d1")
    enqueue(db, "noop", idempotency_key="d2")
    enqueue(db, "flaky", idempotency_key="d3", max_attempts=1)
    counts = drain(db, "w", limit=10, jitter=False)
    assert counts == {"reclaimed": 0, "claimed": 3, "completed": 2, "requeued": 0, "dead": 1}
    heartbeat(db, counts)
    assert db.get(AppState, "jobs_runner").value["completed"] == 2


def test_requeue_resets_a_dead_job(db):
    enqueue(db, "does_not_exist", idempotency_key="rq", max_attempts=1)
    job = run_one(db, claim_next(db, "w"))
    assert job.status == JOB_DEAD
    requeue(db, job)
    assert job.status == JOB_QUEUED and job.last_error is None


def test_execute_ai_run_handler_records_a_demo_observation(db, monkeypatch):
    from app.config import settings
    from app.models import AIRun

    monkeypatch.setattr(settings, "demo_mode", True)
    p = Property(name="Job Court", slug="job-court")
    db.add(p)
    db.commit()
    job, _ = enqueue(
        db, "execute_ai_run",
        {"property_id": p.id, "prompt_text": "best apartments", "platform": "chatgpt"},
        idempotency_key=f"execute_ai_run:{p.id}:chatgpt:test:0", property_id=p.id,
    )
    job = run_one(db, claim_next(db, "w"))
    assert job.status == JOB_COMPLETED
    assert job.result["status"] == "success"
    run = db.get(AIRun, job.result["run_id"])
    assert run.job_id == job.id and run.provider == "demo"


def test_execute_ai_run_final_outcomes_do_not_retry(db, monkeypatch):
    """A discarded (non-browsing) run is a final outcome: the job completes
    with that status instead of re-spending on retries."""
    from app.connectors.base import ProviderResult, ProviderUsage
    from app.services.ai_visibility import providers as providers_mod
    from app.services.ai_visibility.providers import BrowsingUnavailableError

    class NonBrowsing(providers_mod.DemoVisibilityProvider):
        def execute(self, prompt, platform, *, model=None, location=None):
            raise BrowsingUnavailableError(
                "no browse",
                result=ProviderResult(text="", provider="demo", platform=platform,
                                      usage=ProviderUsage(input_tokens=5)),
            )

    monkeypatch.setattr(providers_mod, "get_ai_visibility_provider", lambda platform=None: NonBrowsing())
    p = Property(name="Final Court", slug="final-court")
    db.add(p)
    db.commit()
    enqueue(db, "execute_ai_run", {"property_id": p.id, "prompt_text": "q", "platform": "chatgpt"},
            idempotency_key="final:1")
    job = run_one(db, claim_next(db, "w"))
    assert job.status == JOB_COMPLETED
    assert job.result["status"] == "failed" and job.result["error_class"] == "browsing_unavailable"
