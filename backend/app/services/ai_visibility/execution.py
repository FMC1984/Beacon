"""Query execution orchestrator: enforce cost/rate controls, run the one
non-deterministic step, deterministically parse + store the result, and enqueue
a RAG sync. Every execution is logged for after-the-fact cost auditing.

Phase 19: `run_query` is a thin property-scoped wrapper over
observatory.observe.execute_observation, which writes the run ledger (tokens,
cost, status, including failed/discarded attempts) and the provider-reported
citations and retrieval queries alongside the verbatim response. Signature
and return type are unchanged for the router, the scheduler and the tests."""

import logging
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.config import settings
from app.connectors.base import AIVisibilityQueryProvider
from app.models import AIVisibilityQuery, Property
from app.services.ai_visibility.mentions import resolve_property_terms

logger = logging.getLogger("beacon.ai_visibility")


class RateLimitExceeded(RuntimeError):
    """Per-property daily query budget reached; surfaced honestly, never hidden."""


def _day_start(now: datetime) -> datetime:
    return now.replace(hour=0, minute=0, second=0, microsecond=0)


def queries_used_today(db: Session, property_id: int, now: datetime | None = None) -> int:
    now = now or datetime.now(timezone.utc)
    return (
        db.query(AIVisibilityQuery)
        .filter(
            AIVisibilityQuery.property_id == property_id,
            AIVisibilityQuery.executed_at >= _day_start(now),
        )
        .count()
    )


def budget_status(db: Session, property_id: int, now: datetime | None = None) -> dict:
    used = queries_used_today(db, property_id, now)
    limit = settings.ai_visibility_daily_limit
    return {
        "limit_per_day": limit,
        "used_today": used,
        "remaining_today": max(0, limit - used),
        "exhausted": used >= limit,
    }


def brand_terms_for(prop: Property) -> list[str]:
    """Deterministic brand terms for mention detection: the property name
    plus any operator-asserted aliases (Property.aliases). Beacon never
    invents an alias; if a name is missing there is nothing to match."""
    return resolve_property_terms(prop)


def run_query(
    db: Session,
    property_id: int,
    prompt: str,
    platform: str,
    provider: AIVisibilityQueryProvider | None = None,
    now: datetime | None = None,
    prompt_id: int | None = None,
) -> AIVisibilityQuery:
    from app.services.observatory.observe import execute_observation

    outcome = execute_observation(
        db,
        property_id=property_id,
        prompt_text=prompt,
        platform=platform,
        prompt_id=prompt_id,
        provider=provider,
        now=now,
    )
    assert outcome.response is not None  # success path always stores evidence
    return outcome.response
