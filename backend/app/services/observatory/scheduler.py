"""Adaptive Observatory scheduler (Phase 19, slice 5).

  sync_schedule   one AIRunSchedule row per representative, approved, active
                  prompt x live platform that someone is subscribed to
  priority        weighted 0-1 components from rollups (weights in
                  reference_data/ai_scheduler.json), stored with the decision
  plan_runs       due rows by priority, checked against the organization's
                  monthly budget, enqueued as idempotent jobs (or only logged
                  when dry_run), every decision written to
                  ai_schedule_decisions

The provider's per-property daily cap is still enforced at execution. Only
SQL, hashing and stored rollups are used here: no model calls.
"""

import json
from datetime import date, datetime, timedelta
from functools import lru_cache
from pathlib import Path

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import (
    AIClusterVisibilityDaily,
    AIPromptAssignment,
    AIPromptCluster,
    AIRunSchedule,
    AIScheduleDecision,
    AIVisibilityPrompt,
    Job,
    PropertyContent,
)
from app.services.ai_visibility.reference import is_live_platform
from app.services.jobs.queue import enqueue, utcnow
from app.services.observatory.budgets import budget_summary
from app.services.observatory.observability import log_event
from app.services.observatory.opportunity_score import _search_demand
from app.services.observatory.tenancy import default_organization_id

_REFERENCE = Path(__file__).resolve().parent.parent.parent / "reference_data" / "ai_scheduler.json"
PLATFORMS = ("chatgpt", "gemini", "perplexity", "claude", "copilot")
RUN_JOB_TYPES = ("execute_market_run", "execute_ai_run")
PENDING_JOB_STATUSES = ("queued", "leased", "running")


@lru_cache(maxsize=1)
def config() -> dict:
    return json.loads(_REFERENCE.read_text())


def _utcnow() -> datetime:
    return utcnow()


def live_platforms() -> list[str]:
    return [p for p in PLATFORMS if is_live_platform(p)]


def _subscribers(db: Session, cluster_id: int | None) -> list[int]:
    if cluster_id is None:
        return []
    return [pid for (pid,) in db.query(AIPromptAssignment.property_id).filter(
        AIPromptAssignment.cluster_id == cluster_id, AIPromptAssignment.active.is_(True),
        AIPromptAssignment.property_id.isnot(None)).distinct().all()]


def sync_schedule(db: Session, now: datetime | None = None) -> dict:
    now = now or _utcnow()
    cfg = config()
    platforms = live_platforms()
    created = updated = 0
    prompts = db.query(AIVisibilityPrompt).filter(
        AIVisibilityPrompt.is_representative.is_(True), AIVisibilityPrompt.active.is_(True),
        AIVisibilityPrompt.approved.is_(True), AIVisibilityPrompt.cluster_id.isnot(None),
    ).all()
    keep: set[str] = set()
    for p in prompts:
        if p.property_id is None and not _subscribers(db, p.cluster_id):
            continue  # nobody would be scored by this shared prompt
        tier = cfg["scope_tiers"].get(p.scope, "standard_property")
        if p.property_id is not None and (p.importance or 0) >= cfg["advanced_importance"]:
            tier = "advanced_property"
        t = cfg["tiers"][tier]
        for platform in platforms:
            key = f"{p.id}:{platform}"
            keep.add(key)
            row = db.query(AIRunSchedule).filter_by(schedule_key=key).one_or_none()
            if row is None:
                db.add(AIRunSchedule(
                    organization_id=p.organization_id, prompt_id=p.id, cluster_id=p.cluster_id,
                    property_id=p.property_id, market_id=p.market_id, platform=platform, tier=tier,
                    cadence_days=t["cadence_days"], repeat_count=t["repeat_count"], next_run_at=now,
                    status="active", schedule_key=key,
                ))
                created += 1
            elif row.tier != tier or row.status != "active":
                row.tier, row.cadence_days, row.repeat_count, row.status = tier, t["cadence_days"], t["repeat_count"], "active"
                row.updated_at = now
                updated += 1
    paused = 0
    for row in db.query(AIRunSchedule).filter(AIRunSchedule.status == "active").all():
        if row.schedule_key not in keep:
            row.status, row.updated_at = "paused", now
            paused += 1
    db.commit()
    return {"created": created, "updated": updated, "paused": paused, "platforms": platforms}


def effective_tier(row: AIRunSchedule, now: datetime) -> str:
    if row.tier_override and (row.escalation_until is None or row.escalation_until > now):
        return row.tier_override
    return row.tier


def _visibility_pair(db: Session, cluster_id: int | None, today: date, days: int) -> tuple[float | None, float | None, float | None, float | None]:
    if cluster_id is None:
        return None, None, None, None

    def window(start: date, end: date):
        e, m, w = db.query(
            func.coalesce(func.sum(AIClusterVisibilityDaily.eligible_count), 0),
            func.coalesce(func.sum(AIClusterVisibilityDaily.mentioned_count), 0),
            func.coalesce(func.sum(AIClusterVisibilityDaily.competitor_win_count), 0),
        ).filter(AIClusterVisibilityDaily.cluster_id == cluster_id,
                 AIClusterVisibilityDaily.day >= start, AIClusterVisibilityDaily.day <= end).one()
        return (m / e, w / e) if e else (None, None)

    cur_v, cur_w = window(today - timedelta(days=days - 1), today)
    prev_v, prev_w = window(today - timedelta(days=2 * days - 1), today - timedelta(days=days))
    return cur_v, prev_v, cur_w, prev_w


def priority(db: Session, row: AIRunSchedule, now: datetime) -> tuple[float, dict]:
    cfg = config()
    weights = cfg["priority_weights"]
    prompt = db.get(AIVisibilityPrompt, row.prompt_id)
    cluster = db.get(AIPromptCluster, row.cluster_id) if row.cluster_id else None
    importance = ((cluster.importance if cluster else None) or (prompt.importance if prompt else 3) or 3) / 5
    days = max(row.cadence_days, 7)
    cur_v, prev_v, cur_w, prev_w = _visibility_pair(db, row.cluster_id, now.date(), days)
    volatility = min(1.0, abs(cur_v - prev_v) * 2) if cur_v is not None and prev_v is not None else 0.0
    movement = min(1.0, abs(cur_w - prev_w) * 2) if cur_w is not None and prev_w is not None else 0.0
    subscribers = [row.property_id] if row.property_id else _subscribers(db, row.cluster_id)
    demands = [d for d in (_search_demand(db, pid, cluster.topic_key if cluster else None) for pid in subscribers[:5]) if d is not None]
    search = min(1.0, max(demands) * 4) if demands else 0.0  # 25% of impressions on the topic saturates
    content = 0.0
    if cluster and cluster.topic_key and subscribers:
        since = row.last_run_at or (now - timedelta(days=row.cadence_days))
        changed = db.query(PropertyContent.topics).filter(
            PropertyContent.property_id.in_(subscribers), PropertyContent.content_changed_at >= since).all()
        from app.services.observatory.taxonomy import topic as taxonomy_topic

        semantic = (taxonomy_topic(cluster.topic_key) or {}).get("semantic_topic")
        if any(cluster.topic_key in (t or []) or (semantic and semantic in (t or [])) for (t,) in changed):
            content = 1.0
    staleness = 1.0 if row.last_run_at is None else min(1.0, (now - row.last_run_at).days / max(row.cadence_days, 1))
    components = {
        "importance": round(importance, 4), "volatility": round(volatility, 4),
        "search_opportunity": round(search, 4), "competitor_movement": round(movement, 4),
        "content_change": content, "staleness": round(staleness, 4),
    }
    score = round(100 * sum(weights[k] * components[k] for k in weights), 2)
    return score, components


def plan_runs(db: Session, now: datetime | None = None, dry_run: bool = True, organization_id: int | None = None) -> dict:
    now = now or _utcnow()
    cfg = config()
    org_id = organization_id if organization_id is not None else default_organization_id(db)
    plan_key = f"{'dry' if dry_run else 'plan'}:{org_id}:{now.strftime('%Y-%m-%dT%H:%M:%S')}"
    rows = db.query(AIRunSchedule).filter(AIRunSchedule.status == "active").all()
    for r in rows if not dry_run else []:  # expired escalations fall back to the base tier
        if r.tier_override and r.escalation_until and r.escalation_until <= now:
            r.tier_override, r.escalation_until = None, None
    due = [r for r in rows if r.next_run_at is None or r.next_run_at <= now]
    scored = sorted(((priority(db, r, now), r) for r in due), key=lambda t: (-t[0][0], t[1].id))
    # Budget is charged when a run executes, so runs already queued but not
    # yet executed are reserved here; otherwise two plans could overspend.
    pending = db.query(func.count(Job.id)).filter(
        Job.job_type.in_(RUN_JOB_TYPES), Job.status.in_(PENDING_JOB_STATUSES),
        (Job.organization_id == org_id) | Job.organization_id.is_(None),
    ).scalar() or 0
    remaining = max(0, budget_summary(db, "org", org_id)["remaining_runs"] - pending)
    enqueued = skipped = 0
    decisions = []
    for (score, components), r in scored:
        tier = effective_tier(r, now)
        t = cfg["tiers"][tier]
        repeats = t["repeat_count"]
        if enqueued >= cfg["max_enqueue_per_plan"]:
            decision, reason, job_ids = "deferred", "Plan limit reached; left for the next plan.", []
        elif remaining < repeats:
            decision, reason, job_ids = "skipped_budget", f"Needs {repeats} run(s); {remaining} left this month.", []
            skipped += 1
        else:
            remaining -= repeats
            job_ids = []
            if dry_run:
                decision, reason = "dry_run", f"Would enqueue {repeats} run(s) on {r.platform} ({tier})."
            else:
                prompt = db.get(AIVisibilityPrompt, r.prompt_id)
                for i in range(repeats):
                    if r.property_id is None:
                        job, _ = enqueue(db, "execute_market_run", {"prompt_id": r.prompt_id, "platform": r.platform, "repeat_index": i},
                                         idempotency_key=f"sched:{r.id}:{now.date().isoformat()}:{i}",
                                         market_id=r.market_id, organization_id=org_id, priority=int(score))
                    else:
                        job, _ = enqueue(db, "execute_ai_run", {"property_id": r.property_id, "prompt_text": prompt.prompt_text,
                                         "platform": r.platform, "prompt_id": r.prompt_id, "run_scope": prompt.scope, "repeat_index": i},
                                         idempotency_key=f"sched:{r.id}:{now.date().isoformat()}:{i}",
                                         property_id=r.property_id, organization_id=org_id, priority=int(score))
                    job_ids.append(job.id)
                r.last_run_at = now
                r.next_run_at = now + timedelta(days=t["cadence_days"])
                decision, reason = "enqueued", f"Enqueued {repeats} run(s) on {r.platform} ({tier})."
            enqueued += 1
        if not dry_run:
            r.last_priority_score, r.priority_components = score, components
        db.add(AIScheduleDecision(plan_key=plan_key, schedule_id=r.id, prompt_id=r.prompt_id, decision=decision,
                                  reason=reason, priority_score=score, priority_components=components,
                                  job_ids=job_ids or None, dry_run=dry_run))
        decisions.append({"schedule_id": r.id, "prompt_id": r.prompt_id, "platform": r.platform, "tier": tier,
                          "decision": decision, "reason": reason, "priority_score": score, "components": components})
    db.commit()
    log_event("schedule.plan", plan_key=plan_key, due=len(due), enqueued=enqueued, skipped_budget=skipped, dry_run=dry_run)
    return {"plan_key": plan_key, "dry_run": dry_run, "due": len(due), "selected": enqueued,
            "skipped_budget": skipped, "pending_runs_reserved": pending, "budget_remaining_after": remaining,
            "decisions": decisions}
