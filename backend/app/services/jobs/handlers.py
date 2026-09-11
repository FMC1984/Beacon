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


@register("generate_market_prompts")
def generate_market_prompts_job(db: Session, job: Job) -> dict:
    from app.services.observatory.prompt_library import generate_market_prompts

    out = generate_market_prompts(db, int((job.payload or {}).get("market_id", job.market_id)))
    return {k: v for k, v in out.items() if k != "prompts"}


@register("generate_property_prompts")
def generate_property_prompts_job(db: Session, job: Job) -> dict:
    from app.services.observatory.prompt_library import generate_property_prompts

    out = generate_property_prompts(db, int((job.payload or {}).get("property_id", job.property_id)))
    return {k: v for k, v in out.items() if k != "prompts"}


@register("cluster_prompts")
def cluster_prompts_job(db: Session, job: Job) -> dict:
    from app.services.observatory.clustering import cluster_prompts

    p = job.payload or {}
    report = cluster_prompts(
        db, market_id=p.get("market_id", job.market_id), property_id=p.get("property_id", job.property_id),
        scope=p.get("scope"),
    )
    return {"clusters_total": report.clusters_total, "clusters_created": report.clusters_created,
            "prompts_clustered": report.prompts_clustered, "embedding_model": report.embedded_model}


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
