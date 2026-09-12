"""AI visibility alongside site traffic (Phase 19, slice 6). Beacon AI + Search.

Places the property's AI Visibility (MEASURED from monitoring runs) next to
first-party Google data for the same two windows: GA4 sessions referred by AI
platforms (MEASURED, from the existing referral classifier) with their key
events, and Search Console clicks and impressions. Google enhances the
picture; it is never required, and every missing source is UNAVAILABLE.

Hard wording rule: this is association, never attribution. AI referral
sessions come from people using AI products, which Beacon does not observe;
Beacon's monitoring runs are its own API calls. The Search Console API does
not report AI Overviews or other generative-AI impressions separately, so
that step of the chain is always UNAVAILABLE.
"""

from datetime import date, timedelta

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import GA4SessionsDaily, GSCPerformanceDaily, Property
from app.services.observatory import LABEL_MEASURED, LABEL_UNAVAILABLE
from app.services.observatory.metrics import metrics_for_window
from app.services.reporting import compare, compare_points, previous_window

ASSOCIATION_NOTE = (
    "These figures are shown side by side for context. Moving together is an association, not evidence that one "
    "caused the other: AI referral sessions come from people using AI products, while AI Visibility comes from "
    "Beacon's own monitoring calls."
)
GSC_AI_NOTE = (
    "Search Console does not report AI Overviews or other generative-AI impressions separately through its API, so "
    "Beacon cannot show them."
)


def _latest(db: Session, model, pid: int) -> date | None:
    return db.query(func.max(model.date)).filter(model.property_id == pid).scalar()


def _rows_in(db: Session, model, pid: int, start: date, end: date) -> int:
    return db.query(func.count(model.id)).filter(model.property_id == pid, model.date >= start, model.date <= end).scalar() or 0


def _ga4(db: Session, pid: int, start: date, end: date) -> dict | None:
    """None when GA4 has no rows for this period (not connected, or data ends
    earlier): an uncovered period is UNAVAILABLE, never a zero."""
    if not _rows_in(db, GA4SessionsDaily, pid, start, end):
        return None
    row = db.query(
        func.coalesce(func.sum(GA4SessionsDaily.sessions), 0),
        func.coalesce(func.sum(GA4SessionsDaily.key_events), 0),
    ).filter(GA4SessionsDaily.property_id == pid, GA4SessionsDaily.is_ai_referral.is_(True),
             GA4SessionsDaily.date >= start, GA4SessionsDaily.date <= end).one()
    all_sessions = db.query(func.coalesce(func.sum(GA4SessionsDaily.sessions), 0)).filter(
        GA4SessionsDaily.property_id == pid, GA4SessionsDaily.date >= start, GA4SessionsDaily.date <= end).scalar()
    mix = db.query(GA4SessionsDaily.ai_platform, func.sum(GA4SessionsDaily.sessions)).filter(
        GA4SessionsDaily.property_id == pid, GA4SessionsDaily.is_ai_referral.is_(True),
        GA4SessionsDaily.date >= start, GA4SessionsDaily.date <= end).group_by(GA4SessionsDaily.ai_platform).all()
    return {"ai_sessions": int(row[0]), "ai_key_events": int(row[1]), "all_sessions": int(all_sessions or 0),
            "platform_mix": {p or "unknown": int(n) for p, n in mix}}


def _gsc(db: Session, pid: int, start: date, end: date) -> dict | None:
    if not _rows_in(db, GSCPerformanceDaily, pid, start, end):
        return None
    clicks, impressions = db.query(
        func.coalesce(func.sum(GSCPerformanceDaily.clicks), 0),
        func.coalesce(func.sum(GSCPerformanceDaily.impressions), 0),
    ).filter(GSCPerformanceDaily.property_id == pid, GSCPerformanceDaily.date >= start, GSCPerformanceDaily.date <= end).one()
    return {"clicks": int(clicks), "impressions": int(impressions)}


def _missing_note(source: str, latest: date | None) -> str:
    if latest is None:
        return f"No {source} data for this property."
    return f"No {source} data in this period (latest {latest.isoformat()})."


def _direction(delta: float | None) -> str | None:
    if delta is None:
        return None
    return "up" if delta > 0 else "down" if delta < 0 else "flat"


def impact_summary(db: Session, property_id: int, days: int = 30, today: date | None = None) -> dict:
    today = today or date.today()
    prop = db.get(Property, property_id)
    if prop is None:
        raise ValueError("Property not found.")
    start, end = today - timedelta(days=days - 1), today
    p_start, p_end = previous_window(start, end)
    cur, prev = metrics_for_window(db, property_id, start, end), metrics_for_window(db, property_id, p_start, p_end)
    vis = compare_points(cur["ai_visibility"]["value"], prev["ai_visibility"]["value"])

    ga_cur, ga_prev = _ga4(db, property_id, start, end), _ga4(db, property_id, p_start, p_end)
    gsc_cur, gsc_prev = _gsc(db, property_id, start, end), _gsc(db, property_id, p_start, p_end)
    ga_note = None if ga_cur else _missing_note("GA4", _latest(db, GA4SessionsDaily, property_id))
    gsc_latest = _latest(db, GSCPerformanceDaily, property_id)
    ai_sessions = compare(ga_cur["ai_sessions"], ga_prev["ai_sessions"]) if ga_cur and ga_prev else None

    vis_dir = _direction(vis.get("point_change")) if vis else None
    ses_dir = ai_sessions.get("direction") if ai_sessions else None
    if vis_dir and ses_dir and "flat" not in (vis_dir, ses_dir):
        alignment = "same_direction" if vis_dir == ses_dir else "opposite_directions"
    else:
        alignment = "not_comparable"
    alignment_text = {
        "same_direction": "AI Visibility and AI referral sessions moved in the same direction this period.",
        "opposite_directions": "AI Visibility and AI referral sessions moved in opposite directions this period.",
        "not_comparable": "There is not enough data in both periods to compare their direction.",
    }[alignment]

    chain = [
        {"step": "AI Visibility in monitored answers", "label": LABEL_MEASURED if cur["ai_visibility"]["value"] is not None else LABEL_UNAVAILABLE,
         "current": cur["ai_visibility"]["value"], "previous": prev["ai_visibility"]["value"], "comparison": vis,
         "source": "Beacon monitoring runs"},
        {"step": "AI Overviews and generative-AI impressions", "label": LABEL_UNAVAILABLE, "current": None,
         "previous": None, "comparison": None, "source": "Search Console", "note": GSC_AI_NOTE},
        {"step": "Sessions referred by AI platforms", "label": LABEL_MEASURED if ga_cur else LABEL_UNAVAILABLE,
         "current": ga_cur["ai_sessions"] if ga_cur else None, "previous": ga_prev["ai_sessions"] if ga_prev else None,
         "comparison": ai_sessions, "source": "GA4", "note": ga_note},
        {"step": "Key events from AI-referred sessions", "label": LABEL_MEASURED if ga_cur else LABEL_UNAVAILABLE,
         "current": ga_cur["ai_key_events"] if ga_cur else None, "previous": ga_prev["ai_key_events"] if ga_prev else None,
         "comparison": compare(ga_cur["ai_key_events"], ga_prev["ai_key_events"]) if ga_cur and ga_prev else None,
         "source": "GA4", "note": ga_note},
    ]
    return {
        "property_id": property_id,
        "mode": "ai_plus_search" if (_latest(db, GA4SessionsDaily, property_id) or gsc_latest) else "ai_only",
        "window": {"start": start.isoformat(), "end": end.isoformat(), "days": days},
        "previous_window": {"start": p_start.isoformat(), "end": p_end.isoformat()},
        "chain": chain,
        "search_console": {
            "label": LABEL_MEASURED if gsc_cur else LABEL_UNAVAILABLE,
            "current": gsc_cur, "previous": gsc_prev,
            "clicks": compare(gsc_cur["clicks"], gsc_prev["clicks"]) if gsc_cur and gsc_prev else None,
            "impressions": compare(gsc_cur["impressions"], gsc_prev["impressions"]) if gsc_cur and gsc_prev else None,
            "note": GSC_AI_NOTE if gsc_cur else _missing_note("Search Console", gsc_latest),
        },
        "ai_platform_mix": ga_cur["platform_mix"] if ga_cur else {},
        "alignment": alignment,
        "alignment_text": alignment_text,
        "note": ASSOCIATION_NOTE,
    }
