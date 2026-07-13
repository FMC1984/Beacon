"""GA4 events breakdown, shared by the Dashboard and the SEO report.

Aggregates the ga4_events_daily rows by event name over a scoped window. Event
count is exact and additive; user counts are the sum of each day's active users,
which can exceed unique visitors across a multi-day window, so the section
carries a note saying so rather than presenting a summed figure as if it were a
unique count.
"""

from datetime import date

from sqlalchemy.orm import Session

from app.models import GA4EventsDaily, SourceType
from app.services.metrics import _provenance, _scoped

DEFAULT_LIMIT = 12

USERS_NOTE = (
    "Event counts are exact. User counts sum active users per day, so over a "
    "multi-day window they can exceed the number of unique visitors."
)


def build_events_section(
    db: Session,
    property_ids,
    start: date,
    end: date,
    today: date,
    limit: int = DEFAULT_LIMIT,
) -> dict | None:
    """Top events by count over [start, end] for the scope. Returns None (a real
    'no events data', handled as a named empty state by callers) when the events
    table has nothing in range."""
    rows = _scoped(
        db.query(GA4EventsDaily).filter(
            GA4EventsDaily.date >= start, GA4EventsDaily.date <= end
        ),
        GA4EventsDaily,
        property_ids,
    ).all()
    if not rows:
        return None

    by_event: dict[str, dict] = {}
    total_count = 0
    for r in rows:
        e = by_event.setdefault(
            r.event_name,
            {"event_name": r.event_name, "event_count": 0, "total_users": 0},
        )
        e["event_count"] += r.event_count
        e["total_users"] += r.total_users
        total_count += r.event_count

    events = sorted(by_event.values(), key=lambda e: e["event_count"], reverse=True)
    for e in events:
        e["count_share"] = round(e["event_count"] / total_count, 4) if total_count else None
        e["per_user"] = (
            round(e["event_count"] / e["total_users"], 2) if e["total_users"] else None
        )

    dates = [r.date for r in rows]
    return {
        "total_event_count": total_count,
        "distinct_events": len(events),
        "events": events[:limit],
        "events_shown": min(limit, len(events)),
        "events_total": len(events),
        "note": USERS_NOTE,
        "provenance": _provenance(
            db, SourceType.GA4, property_ids, min(dates), max(dates), today
        ),
    }
