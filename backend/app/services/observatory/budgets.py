"""Monthly observation budgets (Phase 19, slice 1b): the ledger side.
Every AI run attempt is charged to its organization's monthly budget
(runs, plus dollars where a rate exists). Enforcement in the scheduler is
Phase 5; the legacy per-property daily cap remains the hard stop until then."""

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.config import settings
from app.models import AIBudget, AIRun
from app.models.ai_budgets import SCOPE_ORG


def period_key(now: datetime | None = None) -> str:
    now = now or datetime.now(timezone.utc)
    return now.strftime("%Y-%m")


def ensure_budget(
    db: Session,
    scope_type: str,
    scope_id: int,
    period: str,
    default_runs: int | None = None,
) -> AIBudget:
    row = (
        db.query(AIBudget)
        .filter_by(scope_type=scope_type, scope_id=scope_id, period=period)
        .one_or_none()
    )
    if row is None:
        allowance = default_runs
        if allowance is None:
            allowance = settings.ai_org_monthly_run_default if scope_type == SCOPE_ORG else 0
        row = AIBudget(
            scope_type=scope_type, scope_id=scope_id, period=period,
            allowance_runs=allowance, spent_runs=0, spent_usd=0.0,
        )
        db.add(row)
        db.flush()
    return row


def record_spend(db: Session, run: AIRun, organization_id: int | None) -> AIBudget | None:
    """Charge one run attempt to the org's current-month budget. Failed and
    discarded runs count: the provider billed them. Does not commit."""
    if organization_id is None:
        return None
    period = period_key(run.started_at.replace(tzinfo=timezone.utc) if run.started_at else None)
    budget = ensure_budget(db, SCOPE_ORG, organization_id, period)
    budget.spent_runs = (budget.spent_runs or 0) + 1
    budget.spent_usd = round((budget.spent_usd or 0.0) + (run.estimated_cost or 0.0), 6)
    return budget


def budget_summary(db: Session, scope_type: str, scope_id: int, period: str | None = None) -> dict:
    period = period or period_key()
    budget = ensure_budget(db, scope_type, scope_id, period)
    remaining = max(0, budget.allowance_runs - budget.spent_runs)
    return {
        "scope_type": scope_type,
        "scope_id": scope_id,
        "period": period,
        "allowance_runs": budget.allowance_runs,
        "spent_runs": budget.spent_runs,
        "remaining_runs": remaining,
        "exhausted": budget.spent_runs >= budget.allowance_runs,
        "allowance_usd": budget.allowance_usd,
        "spent_usd": budget.spent_usd,
    }
