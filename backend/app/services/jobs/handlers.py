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


@register("execute_market_run")
def execute_market_run(db: Session, job: Job) -> dict:
    """Run one shared market prompt; payload {prompt_id, platform?, repeat_index?}."""
    from app.services.ai_visibility.execution import RateLimitExceeded
    from app.services.observatory.observe import classify_error, execute_market_prompt

    p = job.payload or {}
    try:
        outcome = execute_market_prompt(
            db, int(p["prompt_id"]), platform=p.get("platform"),
            repeat_index=int(p.get("repeat_index", 0)), job_id=job.id,
        )
    except RateLimitExceeded as exc:
        return {"status": "skipped_budget", "detail": str(exc)}
    except ValueError as exc:
        return {"status": "failed", "error_class": "invalid_prompt", "detail": str(exc)[:500]}
    except Exception as exc:
        error_class = classify_error(exc)
        if error_class in RETRYABLE_ERROR_CLASSES:
            raise
        return {"status": "failed", "error_class": error_class, "detail": str(exc)[:500]}
    from app.models import AIPropertyObservation
    from app.services.observatory.rollups import update_market_rollups

    scored = db.query(AIPropertyObservation).filter_by(response_id=outcome.response.id).count() if outcome.response else 0
    if outcome.run.market_id is not None:
        update_market_rollups(db, market_ids=[outcome.run.market_id], days=1)
    return {"status": outcome.run.status, "run_id": outcome.run.id,
            "response_id": outcome.response.id if outcome.response else None, "properties_scored": scored}


@register("derive_observations")
def derive_observations_job(db: Session, job: Job) -> dict:
    from app.services.observatory.derivation import backfill_observations, rederive_response

    p = job.payload or {}
    if p.get("response_id"):
        rows = rederive_response(db, int(p["response_id"]))
        return {"response_id": p["response_id"], "observations": len(rows)}
    return backfill_observations(db, property_id=p.get("property_id", job.property_id))


@register("update_property_rollups")
def update_property_rollups_job(db: Session, job: Job) -> dict:
    from app.services.observatory.rollups import update_property_rollups

    p = job.payload or {}
    ids = p.get("property_ids") or ([job.property_id] if job.property_id else None)
    return update_property_rollups(db, property_ids=ids, full=bool(p.get("full")))


@register("update_market_rollups")
def update_market_rollups_job(db: Session, job: Job) -> dict:
    from app.services.observatory.rollups import update_market_rollups

    p = job.payload or {}
    return update_market_rollups(db, market_ids=p.get("market_ids"))


@register("discover_competitors")
def discover_competitors_job(db: Session, job: Job) -> dict:
    from app.services.observatory.discovery import backfill_discovery

    return backfill_discovery(db, int((job.payload or {}).get("market_id", job.market_id)))


@register("verify_claims")
def verify_claims_job(db: Session, job: Job) -> dict:
    from app.services.observatory.claims import backfill_claims

    return backfill_claims(db, int((job.payload or {}).get("property_id", job.property_id)))


@register("detect_alerts")
def detect_alerts_job(db: Session, job: Job) -> dict:
    from app.models import Property
    from app.services.observatory.alerts import detect_property_alerts, escalate

    p = job.payload or {}
    ids = [p["property_id"]] if p.get("property_id") else [pid for (pid,) in db.query(Property.id).filter(Property.is_active.is_(True))]
    created = escalated = 0
    for pid in ids:
        for alert in detect_property_alerts(db, int(pid)):
            created += 1
            escalated += 1 if escalate(db, alert) else 0
    return {"properties": len(ids), "alerts_created": created, "escalated": escalated}


@register("schedule_ai_runs")
def schedule_ai_runs_job(db: Session, job: Job) -> dict:
    from app.services.observatory.scheduler import plan_runs, sync_schedule

    synced = sync_schedule(db)
    plan = plan_runs(db, dry_run=bool((job.payload or {}).get("dry_run", False)), organization_id=job.organization_id)
    return {"sync": synced, **{k: v for k, v in plan.items() if k != "decisions"}}


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
