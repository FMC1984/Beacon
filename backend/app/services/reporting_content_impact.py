"""Content Impact report (Phase 16F).

For each recorded content change, compares available performance metrics in the
window before the change date against the equal window after. This is an
observational before-and-after, NOT a causal claim: every comparison ships with
the fixed external-factors caveat, and the language never says a change caused a
result.

Metrics compared: Search Console clicks/impressions/CTR/position and GA4
organic sessions/key events. A window whose "after" period has not fully
elapsed yet is reported as still accumulating, never as a drop to zero.
"""

from datetime import date, timedelta

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import ContentChange, GA4SessionsDaily, GSCPerformanceDaily, Property
from app.services.reporting import DataState, compare

# Supported symmetric comparison windows (days before and after the change).
WINDOWS = [14, 30, 60]
DEFAULT_WINDOW = 30

EXTERNAL_FACTORS_CAVEAT = (
    "Observed changes may be influenced by seasonality, competition, demand, "
    "tracking changes, and other external factors. Beacon does not claim the "
    "content change caused the result."
)


def _gsc_metrics(db, property_id, start, end):
    rows = (
        db.query(GSCPerformanceDaily)
        .filter(
            GSCPerformanceDaily.property_id == property_id,
            GSCPerformanceDaily.date >= start,
            GSCPerformanceDaily.date <= end,
        )
        .all()
    )
    if not rows:
        return None
    clicks = sum(r.clicks for r in rows)
    impressions = sum(r.impressions for r in rows)
    pos = (
        sum(r.position * r.impressions for r in rows) / impressions
        if impressions else None
    )
    return {
        "clicks": clicks,
        "impressions": impressions,
        "ctr": round(clicks / impressions, 4) if impressions else None,
        "position": round(pos, 1) if pos is not None else None,
    }


def _ga4_metrics(db, property_id, start, end):
    rows = (
        db.query(GA4SessionsDaily)
        .filter(
            GA4SessionsDaily.property_id == property_id,
            GA4SessionsDaily.date >= start,
            GA4SessionsDaily.date <= end,
            func.lower(GA4SessionsDaily.session_medium) == "organic",
        )
        .all()
    )
    if not rows:
        return None
    return {
        "sessions": sum(r.sessions for r in rows),
        "key_events": sum(r.key_events for r in rows),
    }


_METRIC_LABELS = {
    "clicks": ("Search clicks", True),
    "impressions": ("Search impressions", True),
    "ctr": ("CTR", True),
    "position": ("Average position", False),
    "sessions": ("Organic sessions", True),
    "key_events": ("Organic key events", True),
}


def _window_comparison(db, property_id, change_date: date, days: int, today: date):
    before_start = change_date - timedelta(days=days)
    before_end = change_date - timedelta(days=1)
    after_start = change_date
    after_end = change_date + timedelta(days=days - 1)

    # How much of the "after" window has actually elapsed. A not-yet-complete
    # after window is disclosed, never treated as a real zero/decline.
    after_complete = today > after_end
    after_days_elapsed = max(0, min(days, (today - after_start).days + 1))

    before = {
        **( _gsc_metrics(db, property_id, before_start, before_end) or {} ),
        **( _ga4_metrics(db, property_id, before_start, before_end) or {} ),
    }
    after = {
        **( _gsc_metrics(db, property_id, after_start, after_end) or {} ),
        **( _ga4_metrics(db, property_id, after_start, after_end) or {} ),
    }

    metrics = []
    for key, (label, higher_better) in _METRIC_LABELS.items():
        b = before.get(key)
        a = after.get(key)
        if b is None and a is None:
            state = DataState.EMPTY.value
        elif not after_complete:
            state = DataState.PARTIAL_PERIOD.value
        else:
            state = DataState.COMPLETE.value
        metrics.append({
            "key": key,
            "label": label,
            "higher_is_better": higher_better,
            "before": b,
            "after": a,
            # Comparison is shown, but only described as an observed change.
            "comparison": compare(a, b) if (a is not None and b is not None) else None,
            "state": state,
        })

    return {
        "days": days,
        "before_window": {"start": before_start.isoformat(), "end": before_end.isoformat()},
        "after_window": {"start": after_start.isoformat(), "end": after_end.isoformat()},
        "after_complete": after_complete,
        "after_days_elapsed": after_days_elapsed,
        "metrics": metrics,
        "caveat": EXTERNAL_FACTORS_CAVEAT,
    }


def build_content_impact_report(
    db: Session, property_id: int | None, window: int = DEFAULT_WINDOW,
    today: date | None = None,
) -> dict:
    today = today or date.today()
    if window not in WINDOWS:
        window = DEFAULT_WINDOW
    if property_id is None:
        return {
            "scope_required": True,
            "message": "Select a single property to view its Content Impact report.",
        }
    prop = db.get(Property, property_id)
    if prop is None:
        raise ValueError("Property not found.")

    changes = (
        db.query(ContentChange)
        .filter_by(property_id=property_id)
        .order_by(ContentChange.date_implemented.desc(), ContentChange.id.desc())
        .all()
    )

    items = []
    for c in changes:
        items.append({
            "id": c.id,
            "change_title": c.change_title,
            "change_type": c.change_type.value,
            "date_implemented": c.date_implemented.isoformat(),
            "page_url": c.page_url,
            "notes": c.notes,
            "related_opportunity": c.related_opportunity,
            "comparison": _window_comparison(db, property_id, c.date_implemented, window, today),
        })

    # Timeline of change dates for annotating other report charts.
    timeline = [
        {"date": c.date_implemented.isoformat(), "title": c.change_title, "type": c.change_type.value}
        for c in sorted(changes, key=lambda x: x.date_implemented)
    ]

    return {
        "scope_required": False,
        "property_id": property_id,
        "property_name": prop.name,
        "window": window,
        "available_windows": WINDOWS,
        "caveat": EXTERNAL_FACTORS_CAVEAT,
        "has_changes": bool(changes),
        "changes": items,
        "timeline": timeline,
        "generated_on": today.isoformat(),
    }
