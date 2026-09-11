"""Job handlers (Phase 19). A handler takes (db, job) and returns a JSON-able
result dict. Raising means "retry with backoff"; returning a result with a
non-success status means "this outcome is final" (a discarded provider run
must not be re-spent). Later phases register the remaining job types here."""

from typing import Callable

from sqlalchemy.orm import Session

from app.models import Job

HANDLERS: dict[str, Callable[[Session, Job], dict]] = {}

# Provider error classes worth retrying; everything else is final.
RETRYABLE_ERROR_CLASSES = {"rate_limit", "provider_unavailable", "provider_error_5xx"}


def register(job_type: str):
    def _wrap(fn: Callable[[Session, Job], dict]):
        HANDLERS[job_type] = fn
        return fn

    return _wrap


@register("noop")
def noop(db: Session, job: Job) -> dict:
    return {"ok": True, "payload": job.payload or {}}


@register("execute_ai_run")
def execute_ai_run(db: Session, job: Job) -> dict:
    """Run one prompt against one platform through the Observatory ledger.
    payload: {property_id, prompt_text, platform, prompt_id?, run_scope?,
    market_id?, repeat_index?}."""
    from app.services.ai_visibility.execution import RateLimitExceeded
    from app.services.observatory.observe import classify_error, execute_observation

    p = job.payload or {}
    try:
        outcome = execute_observation(
            db,
            property_id=p.get("property_id", job.property_id),
            prompt_text=p.get("prompt_text", ""),
            platform=p.get("platform", "chatgpt"),
            run_scope=p.get("run_scope", "property"),
            prompt_id=p.get("prompt_id"),
            organization_id=job.organization_id,
            market_id=p.get("market_id", job.market_id),
            repeat_index=int(p.get("repeat_index", 0)),
            job_id=job.id,
        )
    except RateLimitExceeded as exc:
        # Daily cap: final for today; the scheduler decides when to try again.
        return {"status": "skipped_budget", "detail": str(exc)}
    except Exception as exc:
        error_class = classify_error(exc)
        if error_class in RETRYABLE_ERROR_CLASSES:
            raise
        return {"status": "failed", "error_class": error_class, "detail": str(exc)[:500]}
    run = outcome.run
    return {
        "status": run.status,
        "run_id": run.id,
        "response_id": outcome.response.id if outcome.response else None,
        "estimated_cost": run.estimated_cost,
    }
