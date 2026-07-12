"""Query execution orchestrator: enforce cost/rate controls, run the one
non-deterministic step, deterministically parse + store the result, and enqueue
a RAG sync. Every execution is logged for after-the-fact cost auditing."""

import logging
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.config import settings
from app.connectors.base import AIVisibilityQueryProvider
from app.extensions.hooks import trigger_rag_sync
from app.models import AIVisibilityQuery, Property
from app.services.ai_visibility.parsing import detect_mention, extract_sources
from app.services.ai_visibility.providers import get_ai_visibility_provider
from app.services.ai_visibility.reference import validate_platform

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
    """Deterministic brand terms for mention detection: the property name only.
    Beacon never invents aliases; if a name is missing there is nothing to
    match."""
    return [prop.name] if prop and prop.name else []


def run_query(
    db: Session,
    property_id: int,
    prompt: str,
    platform: str,
    provider: AIVisibilityQueryProvider | None = None,
    now: datetime | None = None,
) -> AIVisibilityQuery:
    prompt = (prompt or "").strip()
    if not prompt:
        raise ValueError("Prompt is empty.")
    platform = validate_platform(platform)
    prop = db.get(Property, property_id)
    if prop is None:
        raise ValueError("Property not found.")

    now = now or datetime.now(timezone.utc)
    used = queries_used_today(db, property_id, now)
    limit = settings.ai_visibility_daily_limit
    if used >= limit:
        logger.warning(
            "ai_visibility rate limit hit: property=%s used=%s limit=%s",
            property_id, used, limit,
        )
        raise RateLimitExceeded(
            f"Daily AI Visibility query budget reached for this property "
            f"({used}/{limit}). Queries are paused until tomorrow (UTC) so "
            "external-API cost stays bounded."
        )

    provider = provider or get_ai_visibility_provider()
    # The ONLY non-deterministic step in the system.
    raw = provider.execute_query(prompt, platform)
    logger.info(
        "ai_visibility query executed: property=%s platform=%s prompt_chars=%s "
        "response_chars=%s (%s/%s today)",
        property_id, platform, len(prompt), len(raw or ""), used + 1, limit,
    )

    # Everything below here is deterministic given `raw`.
    brand_mentioned = detect_mention(raw, brand_terms_for(prop))
    sources = extract_sources(raw)

    row = AIVisibilityQuery(
        property_id=property_id,
        platform=platform,
        prompt_text=prompt,
        raw_response_text=raw,
        executed_at=now,
        brand_mentioned=brand_mentioned,
        sources_cited=sources,
    )
    db.add(row)
    db.commit()
    db.refresh(row)
    trigger_rag_sync(
        db, property_id=property_id, source="ai_visibility", reason="ai_visibility_query"
    )
    return row
