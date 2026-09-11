"""Phase 19 (1b): monthly observation budgets accrue from the run ledger.
Every attempt is charged (failed runs cost money too); the default
organization gets Tina's 300 runs/month allowance."""

from datetime import datetime, timezone

import pytest

from app.config import settings
from app.models import Property
from app.models.ai_budgets import SCOPE_ORG
from app.services.ai_visibility.execution import run_query
from app.services.ai_visibility.providers import DemoVisibilityProvider
from app.services.observatory.budgets import budget_summary, ensure_budget, period_key
from app.services.observatory.tenancy import default_organization_id
from tests.test_obs_runs import FR, Exploding

NOW = datetime(2026, 9, 10, 12, 0, tzinfo=timezone.utc)


def test_default_org_allowance_matches_setting(db):
    org_id = default_organization_id(db)
    budget = ensure_budget(db, SCOPE_ORG, org_id, "2026-09")
    assert budget.allowance_runs == settings.ai_org_monthly_run_default == 300
    assert budget.spent_runs == 0


def test_runs_charge_the_org_budget_including_failures(db):
    p = Property(name="Budget Ledger Court", slug="budget-ledger-court")
    db.add(p)
    db.commit()
    org_id = default_organization_id(db)

    run_query(db, p.id, "q", "chatgpt", provider=DemoVisibilityProvider(), now=NOW)
    run_query(db, p.id, "q2", "chatgpt", provider=FR("plain answer"), now=NOW)
    with pytest.raises(RuntimeError):
        run_query(db, p.id, "q3", "chatgpt", provider=Exploding("x"), now=NOW)

    summary = budget_summary(db, SCOPE_ORG, org_id, period_key(NOW))
    assert summary["spent_runs"] == 3
    assert summary["remaining_runs"] == 297
    assert summary["exhausted"] is False
    assert summary["spent_usd"] == 0.0  # demo is free, the others are unpriced (None)
