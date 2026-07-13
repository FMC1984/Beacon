"""Reporting foundation (Phase 16A).

Composes existing data into report-ready shapes. This module owns only
presentation-neutral arithmetic: period windows, comparisons, percentage
change, data-state resolution, sampled rates, and source freshness. It never
scores, gates, or recommends; that stays in the intelligence modules it
reads from.

Truth rules enforced here (Phase 16 spec):
- Missing, unknown, or unconfigured data is a named state, never numeric zero.
- A percentage change is computed only when both periods have usable values
  and a nonzero baseline; otherwise the comparison field is null.
- Every sampled rate carries its numerator and denominator.
- Period coverage is declared explicitly so the UI can warn on mismatch.
"""

import enum
from datetime import date, datetime, timedelta

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import (
    AIVisibilityPrompt,
    AIVisibilityQuery,
    DataConnection,
    GA4SessionsDaily,
    GSCPerformanceDaily,
    OAuthStatus,
    PropertyReview,
    RAGChunk,
    SourceType,
)
from app.services.metrics import FRESHNESS_THRESHOLD_DAYS, _resolve_scope, _scoped

# Google-connected sources report daily with a short pipeline lag; data this
# recent is "delayed", not "partial". Manual uploads use the existing weekly
# cadence threshold from the dashboard.
CONNECTED_DELAY_TOLERANCE_DAYS = 3


class DataState(str, enum.Enum):
    COMPLETE = "complete"
    PARTIAL_PERIOD = "partial_period"
    AWAITING_DATA = "awaiting_data"
    SOURCE_DELAYED = "source_delayed"
    NOT_CONFIGURED = "not_configured"
    INSUFFICIENT_SAMPLE = "insufficient_sample"
    FAILED_SOURCE = "failed_source"
    EMPTY = "empty"


# How alarming each state is for the control bar chip. "Not configured" is
# informational, not a problem; a delayed or failed source is.
STATE_SEVERITY: dict[str, int] = {
    DataState.COMPLETE.value: 0,
    DataState.NOT_CONFIGURED.value: 0,
    DataState.AWAITING_DATA.value: 1,
    DataState.EMPTY.value: 1,
    DataState.INSUFFICIENT_SAMPLE.value: 1,
    DataState.PARTIAL_PERIOD.value: 2,
    DataState.SOURCE_DELAYED.value: 2,
    DataState.FAILED_SOURCE.value: 3,
}


def previous_window(start: date, end: date) -> tuple[date, date]:
    """The adjacent, equal-length period immediately before [start, end]."""
    length = (end - start).days + 1
    prev_end = start - timedelta(days=1)
    return prev_end - timedelta(days=length - 1), prev_end


def pct_change(current: float | None, previous: float | None) -> float | None:
    """Fractional change vs the previous value. Null (never zero) when either
    value is missing or the baseline is zero; a rate from a zero or missing
    baseline is a fabrication, not a metric."""
    if current is None or previous is None or previous == 0:
        return None
    return (current - previous) / previous


def compare(current: float | None, previous: float | None) -> dict:
    """Comparison envelope for a metric across two periods. Direction is only
    stated when both values exist; a missing side never masquerades as 0."""
    change = (
        current - previous if current is not None and previous is not None else None
    )
    direction = None
    if change is not None:
        direction = "up" if change > 0 else "down" if change < 0 else "flat"
    return {
        "current": current,
        "previous": previous,
        "change": change,
        "pct_change": pct_change(current, previous),
        "direction": direction,
    }


def rate(numerator: int, denominator: int, minimum_sample: int = 1) -> dict:
    """A sampled rate that always travels with its sample. Below the minimum
    sample (or with an empty denominator) the value is null and the state says
    why, so the UI can render 'insufficient sample' instead of a fake 0%."""
    ok = denominator >= max(minimum_sample, 1)
    return {
        "value": round(numerator / denominator, 4) if ok else None,
        "numerator": numerator,
        "denominator": denominator,
        "minimum_sample": minimum_sample,
        "state": (DataState.COMPLETE if ok else DataState.INSUFFICIENT_SAMPLE).value,
    }


def coverage_state(
    window_start: date,
    window_end: date,
    first_data: date | None,
    last_data: date | None,
    configured: bool,
    delay_tolerance_days: int,
) -> dict:
    """Classify how well a source's data covers a requested window.

    Deterministic rules, in order: unconfigured sources are NOT_CONFIGURED;
    configured sources with no data at all are AWAITING_DATA; data that misses
    the window entirely is EMPTY; a gap only at the tail within the source's
    normal reporting lag is SOURCE_DELAYED; any other gap is PARTIAL_PERIOD.
    """
    if not configured:
        state = DataState.NOT_CONFIGURED
    elif first_data is None or last_data is None:
        state = DataState.AWAITING_DATA
    elif last_data < window_start or first_data > window_end:
        state = DataState.EMPTY
    else:
        head_covered = first_data <= window_start
        tail_gap = (window_end - last_data).days
        if head_covered and tail_gap <= 0:
            state = DataState.COMPLETE
        elif head_covered and tail_gap <= delay_tolerance_days:
            state = DataState.SOURCE_DELAYED
        else:
            state = DataState.PARTIAL_PERIOD
    covered_start = (
        max(first_data, window_start)
        if first_data and last_data and state not in (DataState.EMPTY,)
        else None
    )
    covered_end = (
        min(last_data, window_end)
        if first_data and last_data and state not in (DataState.EMPTY,)
        else None
    )
    return {
        "state": state.value,
        "covered_start": covered_start.isoformat() if covered_start else None,
        "covered_end": covered_end.isoformat() if covered_end else None,
    }


def comparable(current_coverage: dict, previous_coverage: dict) -> dict:
    """Whether two periods may be compared without a warning: both must have
    usable data, and both must be complete (or merely delayed). Anything else
    yields a comparison warning the UI is required to surface."""
    usable = {DataState.COMPLETE.value, DataState.SOURCE_DELAYED.value}
    ok = (
        current_coverage["state"] in usable
        and previous_coverage["state"] in usable
    )
    return {
        "comparable": ok,
        "warning": (
            None
            if ok
            else "Periods have incompatible source coverage and are not compared."
        ),
    }


# ---------------------------------------------------------------------------
# Source status (powers the report control bar freshness indicator and the
# data status strip). Read-only composition over existing tables.
# ---------------------------------------------------------------------------


def _google_connected(db: Session, source: SourceType, property_ids) -> bool:
    q = db.query(func.count(DataConnection.id)).filter(
        DataConnection.source_type == source,
        DataConnection.oauth_status == OAuthStatus.CONNECTED,
    )
    if property_ids is not None:
        q = q.filter(DataConnection.property_id.in_(property_ids))
    return bool(q.scalar())


def _daily_source_status(
    db: Session,
    key: str,
    label: str,
    model,
    source: SourceType,
    property_ids,
    today: date,
) -> dict:
    first = _scoped(db.query(func.min(model.date)), model, property_ids).scalar()
    last = _scoped(db.query(func.max(model.date)), model, property_ids).scalar()
    connected = _google_connected(db, source, property_ids)
    configured = connected or last is not None
    tolerance = (
        CONNECTED_DELAY_TOLERANCE_DAYS if connected else FRESHNESS_THRESHOLD_DAYS
    )
    if not configured:
        state, detail = DataState.NOT_CONFIGURED, "Not connected and no uploads."
    elif last is None:
        state, detail = DataState.AWAITING_DATA, "Connected, first sync pending."
    elif (today - last).days > tolerance:
        state = DataState.SOURCE_DELAYED
        detail = f"Complete through {last.isoformat()}, older than expected."
    else:
        state, detail = DataState.COMPLETE, f"Complete through {last.isoformat()}."
    return {
        "key": key,
        "label": label,
        "state": state.value,
        "detail": detail,
        "first_data_date": first.isoformat() if first else None,
        "last_data_date": last.isoformat() if last else None,
        "connected": connected,
    }


def _ai_visibility_status(db: Session, property_ids) -> dict:
    q = db.query(func.max(AIVisibilityQuery.executed_at))
    if property_ids is not None:
        q = q.filter(AIVisibilityQuery.property_id.in_(property_ids))
    last_run: datetime | None = q.scalar()
    prompts = db.query(func.count(AIVisibilityPrompt.id))
    if property_ids is not None:
        prompts = prompts.filter(AIVisibilityPrompt.property_id.in_(property_ids))
    prompt_count = prompts.scalar() or 0
    if last_run is None and prompt_count == 0:
        state, detail = DataState.NOT_CONFIGURED, "No visibility runs yet."
    elif last_run is None:
        state = DataState.AWAITING_DATA
        detail = f"{prompt_count} standing prompt(s) saved, never run."
    else:
        state = DataState.COMPLETE
        detail = f"Last run {last_run.date().isoformat()}."
    return {
        "key": "ai_visibility",
        "label": "AI Visibility",
        "state": state.value,
        "detail": detail,
        "first_data_date": None,
        "last_data_date": last_run.date().isoformat() if last_run else None,
        "connected": False,
    }


def _reviews_status(db: Session, property_ids) -> dict:
    q = db.query(
        func.count(PropertyReview.id), func.max(PropertyReview.review_date)
    )
    if property_ids is not None:
        q = q.filter(PropertyReview.property_id.in_(property_ids))
    count, newest = q.one()
    if not count:
        state, detail = DataState.NOT_CONFIGURED, "No reviews ingested."
    else:
        state = DataState.COMPLETE
        detail = f"{count} review(s), newest {newest.isoformat()}."
    return {
        "key": "reviews",
        "label": "Reviews",
        "state": state.value,
        "detail": detail,
        "first_data_date": None,
        "last_data_date": newest.isoformat() if newest else None,
        "connected": False,
    }


def _rag_status(db: Session, property_ids) -> dict:
    q = db.query(
        func.count(RAGChunk.id),
        func.max(func.coalesce(RAGChunk.updated_at, RAGChunk.created_at)),
    )
    if property_ids is not None:
        q = q.filter(RAGChunk.property_id.in_(property_ids))
    count, newest = q.one()
    if not count:
        state, detail = DataState.AWAITING_DATA, "No content indexed for this scope."
    else:
        state = DataState.COMPLETE
        detail = f"{count} chunk(s) indexed."
    newest_date = newest.date().isoformat() if isinstance(newest, datetime) else (
        str(newest)[:10] if newest else None
    )
    return {
        "key": "rag_index",
        "label": "Knowledge index",
        "state": state.value,
        "detail": detail,
        "first_data_date": None,
        "last_data_date": newest_date,
        "connected": False,
    }


def source_status(
    db: Session,
    property_id: int | None,
    company_id: int | None = None,
    unassigned: bool = False,
    today: date | None = None,
) -> dict:
    """Per-source freshness for the report control bar and data status strip.
    Scope resolution is identical to the dashboard's (server-side, never
    trusted from the frontend filter alone)."""
    today = today or date.today()
    property_ids = _resolve_scope(db, property_id, company_id, unassigned)
    sources = [
        _daily_source_status(
            db, "ga4", "GA4", GA4SessionsDaily, SourceType.GA4, property_ids, today
        ),
        _daily_source_status(
            db,
            "gsc",
            "Search Console",
            GSCPerformanceDaily,
            SourceType.GSC,
            property_ids,
            today,
        ),
        _ai_visibility_status(db, property_ids),
        _reviews_status(db, property_ids),
        _rag_status(db, property_ids),
    ]
    worst = max(sources, key=lambda s: STATE_SEVERITY[s["state"]])["state"]
    return {
        "checked_date": today.isoformat(),
        "sources": sources,
        "worst_state": worst,
    }
