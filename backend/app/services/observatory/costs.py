"""Observatory cost and usage reporting (Phase 19, slice 5).

Every attempt in ai_runs carries tokens, search operations and an
estimated_cost that is MODELED from provider-reported usage and the rate
table, or null (UNAVAILABLE) when no rate is configured. Totals therefore
say how much of the spend is priced: a sum over partly-priced runs is a
lower bound and is labeled so, never presented as the full cost.
"""

from datetime import date, datetime, timedelta

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import AIPropertyObservation, AIRun
from app.services.observatory import LABEL_MODELED, LABEL_OBSERVED, LABEL_UNAVAILABLE
from app.services.observatory.budgets import budget_summary
from app.services.observatory.tenancy import default_organization_id


def _cost_block(priced_runs: int, total_runs: int, usd: float | None) -> dict:
    if total_runs == 0:
        return {"estimated_usd": 0.0, "label": LABEL_MODELED, "coverage": "no_runs", "priced_runs": 0, "runs": 0}
    if priced_runs == 0:
        return {"estimated_usd": None, "label": LABEL_UNAVAILABLE, "coverage": "none", "priced_runs": 0, "runs": total_runs,
                "note": "No rates are configured for the models used, so no dollar figure is shown."}
    coverage = "full" if priced_runs == total_runs else "partial"
    return {
        "estimated_usd": round(usd or 0.0, 4), "label": LABEL_MODELED, "coverage": coverage,
        "priced_runs": priced_runs, "runs": total_runs,
        "note": None if coverage == "full" else
        f"Only {priced_runs} of {total_runs} runs have a configured rate; this is a lower bound.",
    }


def cost_report(
    db: Session, days: int = 30, today: date | None = None, property_id: int | None = None,
    market_id: int | None = None, organization_id: int | None = None,
) -> dict:
    today = today or date.today()
    start = datetime.combine(today - timedelta(days=days - 1), datetime.min.time())
    end = datetime.combine(today + timedelta(days=1), datetime.min.time())
    q = db.query(AIRun).filter(AIRun.started_at >= start, AIRun.started_at < end)
    if property_id is not None:
        q = q.filter(AIRun.property_id == property_id)
    if market_id is not None:
        q = q.filter(AIRun.market_id == market_id)
    if organization_id is not None:
        q = q.filter(AIRun.organization_id == organization_id)
    runs = q.all()

    def summarize(rows: list[AIRun]) -> dict:
        priced = [r for r in rows if r.estimated_cost is not None]
        return {
            "runs": len(rows),
            "by_status": {s: sum(1 for r in rows if r.status == s) for s in sorted({r.status for r in rows})},
            "tokens": {
                "label": LABEL_OBSERVED,
                "input": sum(r.token_input or 0 for r in rows),
                "output": sum(r.token_output or 0 for r in rows),
                "reasoning": sum(r.token_reasoning or 0 for r in rows),
                "cached": sum(r.token_cached or 0 for r in rows),
            },
            "search_operations": sum(r.search_operations or 0 for r in rows),
            "cost": _cost_block(len(priced), len(rows), sum(r.estimated_cost for r in priced) if priced else None),
        }

    by_key = lambda key: {  # noqa: E731
        k: summarize([r for r in runs if key(r) == k]) for k in sorted({key(r) for r in runs}, key=str)
    }
    success_ids = [r.id for r in runs if r.status == "success"]
    observations = (
        db.query(func.count(AIPropertyObservation.id)).filter(AIPropertyObservation.run_id.in_(success_ids)).scalar()
        if success_ids else 0
    )
    total = summarize(runs)
    per_observation = None
    if total["cost"]["estimated_usd"] and observations:
        per_observation = {
            "estimated_usd": round(total["cost"]["estimated_usd"] / observations, 5),
            "label": LABEL_MODELED,
            "note": "Run cost divided across every property score it produced (shared market runs spread their cost).",
        }
    org_id = organization_id if organization_id is not None else default_organization_id(db)
    return {
        "window": {"start": start.date().isoformat(), "end": today.isoformat(), "days": days},
        "total": total,
        "by_provider_model": by_key(lambda r: f"{r.provider}:{r.model or r.model_requested or 'unknown'}"),
        "by_scope": by_key(lambda r: r.run_scope),
        "by_day": by_key(lambda r: r.started_at.date().isoformat()),
        "observations_produced": observations,
        "cost_per_observation": per_observation,
        "budget": budget_summary(db, "org", org_id),
        "note": "Runs are Beacon's monitoring API calls. Failed and discarded runs are included because they still spend.",
    }
