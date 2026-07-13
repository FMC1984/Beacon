"""Dashboard metrics aggregation.

Every section returned here carries a provenance envelope (build plan 5.3):
source, actual covered date range, last updated timestamp, and a freshness
warning when the newest data is older than the expected manual-upload cadence.
The GA4 section additionally carries the undercount disclosure; the router and
schema guarantee an AI figure never travels without it (hard rule 3).

The reporting window is anchored to the newest data date in scope rather than
today, because manual exports always trail the calendar; freshness (measured
against today) is reported separately and honestly.
"""

from datetime import date, datetime, timedelta

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.constants import AI_TRAFFIC_DISCLOSURE
from app.models import (
    CRMLead,
    GA4SessionsDaily,
    GBPMetricsDaily,
    GSCPerformanceDaily,
    PaidMediaDaily,
    Property,
    SourceType,
    Upload,
)
from app.services.classifier import get_classifier

# Manual uploads are expected roughly weekly; past this the data is flagged stale.
FRESHNESS_THRESHOLD_DAYS = 14

SOURCE_LABELS = {
    SourceType.GA4: "GA4 manual upload",
    SourceType.GSC: "Search Console manual upload",
    SourceType.GBP: "Business Profile manual upload",
    SourceType.PAID_MEDIA: "Paid media manual upload",
    SourceType.CRM: "CRM manual upload",
}


def _scoped(query, model, property_ids: list[int] | None):
    """property_ids: None = all properties; a list = restrict to those ids
    (an empty list restricts to nothing, e.g. a company with no properties)."""
    if property_ids is not None:
        query = query.filter(model.property_id.in_(property_ids))
    return query


def _resolve_scope(
    db: Session,
    property_id: int | None,
    company_id: int | None,
    unassigned: bool = False,
) -> list[int] | None:
    """Turn a scope request into an explicit id filter. Precedence:
    property_id, then unassigned (properties with no company), then a company's
    properties; otherwise None = the whole portfolio."""
    if property_id is not None:
        return [property_id]
    if unassigned:
        return [
            pid
            for (pid,) in db.query(Property.id)
            .filter(Property.company_id.is_(None))
            .all()
        ]
    if company_id is not None:
        return [
            pid
            for (pid,) in db.query(Property.id)
            .filter(Property.company_id == company_id)
            .all()
        ]
    return None


def _freshness_warning(source_label: str, newest: date, today: date) -> str | None:
    if (today - newest).days > FRESHNESS_THRESHOLD_DAYS:
        return (
            "Data may be out of date. Latest "
            f"{source_label} data is from {newest.isoformat()}."
        )
    return None


def _provenance(
    db: Session,
    source_type: SourceType,
    property_ids: list[int] | None,
    date_min: date,
    date_max: date,
    today: date,
) -> dict:
    label = SOURCE_LABELS[source_type]
    last_uploaded: datetime | None = _scoped(
        db.query(func.max(Upload.uploaded_at)).filter(
            Upload.source_type == source_type
        ),
        Upload,
        property_ids,
    ).scalar()
    return {
        "source": label,
        "date_start": date_min.isoformat(),
        "date_end": date_max.isoformat(),
        "last_updated": last_uploaded.isoformat() if last_uploaded else None,
        "freshness_warning": _freshness_warning(label, date_max, today),
    }


def _anchor_date(db: Session, property_ids: list[int] | None) -> date | None:
    """Newest data date across traffic sources in scope."""
    candidates = []
    for model in (GA4SessionsDaily, GSCPerformanceDaily, GBPMetricsDaily, PaidMediaDaily):
        newest = _scoped(db.query(func.max(model.date)), model, property_ids).scalar()
        if newest:
            candidates.append(newest)
    return max(candidates) if candidates else None


def _ga4_section(db, property_ids, start, end, today):
    q = _scoped(
        db.query(GA4SessionsDaily).filter(
            GA4SessionsDaily.date >= start, GA4SessionsDaily.date <= end
        ),
        GA4SessionsDaily,
        property_ids,
    )
    rows = q.all()
    if not rows:
        return None

    sessions = sum(r.sessions for r in rows)
    ai_rows = [r for r in rows if r.is_ai_referral]
    ai_sessions = sum(r.sessions for r in ai_rows)
    key_events = sum(r.key_events for r in rows)
    ai_key_events = sum(r.key_events for r in ai_rows)

    trend: dict[date, dict] = {}
    for r in rows:
        day = trend.setdefault(r.date, {"sessions": 0, "ai_sessions": 0})
        day["sessions"] += r.sessions
        if r.is_ai_referral:
            day["ai_sessions"] += r.sessions

    labels = {p.key: p.label for p in get_classifier().platforms}
    mix: dict[str, int] = {}
    for r in ai_rows:
        mix[r.ai_platform] = mix.get(r.ai_platform, 0) + r.sessions

    dates = [r.date for r in rows]
    return {
        "sessions": sessions,
        "ai_sessions": ai_sessions,
        "ai_share": round(ai_sessions / sessions, 4) if sessions else 0.0,
        "key_events": key_events,
        "ai_key_events": ai_key_events,
        "trend": [
            {"date": d.isoformat(), **v} for d, v in sorted(trend.items())
        ],
        "platform_mix": sorted(
            (
                {"platform": k, "label": labels.get(k, k), "sessions": v}
                for k, v in mix.items()
            ),
            key=lambda item: -item["sessions"],
        ),
        "disclosure": AI_TRAFFIC_DISCLOSURE,
        "provenance": _provenance(
            db, SourceType.GA4, property_ids, min(dates), max(dates), today
        ),
    }


def _gsc_section(db, property_ids, start, end, today):
    q = _scoped(
        db.query(GSCPerformanceDaily).filter(
            GSCPerformanceDaily.date >= start, GSCPerformanceDaily.date <= end
        ),
        GSCPerformanceDaily,
        property_ids,
    )
    rows = q.all()
    if not rows:
        return None
    clicks = sum(r.clicks for r in rows)
    impressions = sum(r.impressions for r in rows)
    weighted_position = (
        sum(r.position * r.impressions for r in rows) / impressions
        if impressions
        else 0.0
    )
    dates = [r.date for r in rows]
    return {
        "clicks": clicks,
        "impressions": impressions,
        "ctr": round(clicks / impressions, 4) if impressions else 0.0,
        "avg_position": round(weighted_position, 1),
        "provenance": _provenance(
            db, SourceType.GSC, property_ids, min(dates), max(dates), today
        ),
    }


def _gbp_section(db, property_ids, start, end, today):
    q = _scoped(
        db.query(GBPMetricsDaily).filter(
            GBPMetricsDaily.date >= start, GBPMetricsDaily.date <= end
        ),
        GBPMetricsDaily,
        property_ids,
    )
    rows = q.all()
    if not rows:
        return None
    dates = [r.date for r in rows]
    return {
        "search_impressions": sum(r.search_impressions for r in rows),
        "maps_impressions": sum(r.maps_impressions for r in rows),
        "website_clicks": sum(r.website_clicks for r in rows),
        "calls": sum(r.calls for r in rows),
        "direction_requests": sum(r.direction_requests for r in rows),
        "provenance": _provenance(
            db, SourceType.GBP, property_ids, min(dates), max(dates), today
        ),
    }


def _paid_section(db, property_ids, start, end, today):
    q = _scoped(
        db.query(PaidMediaDaily).filter(
            PaidMediaDaily.date >= start, PaidMediaDaily.date <= end
        ),
        PaidMediaDaily,
        property_ids,
    )
    rows = q.all()
    if not rows:
        return None
    by_platform: dict[str, dict] = {}
    for r in rows:
        agg = by_platform.setdefault(
            r.platform, {"spend": 0.0, "clicks": 0, "impressions": 0, "conversions": 0.0}
        )
        agg["spend"] += float(r.spend)
        agg["clicks"] += r.clicks
        agg["impressions"] += r.impressions
        agg["conversions"] += r.conversions
    dates = [r.date for r in rows]
    return {
        "spend": round(sum(p["spend"] for p in by_platform.values()), 2),
        "clicks": sum(p["clicks"] for p in by_platform.values()),
        "impressions": sum(p["impressions"] for p in by_platform.values()),
        "conversions": round(sum(p["conversions"] for p in by_platform.values()), 1),
        "by_platform": [
            {"platform": k, **{kk: round(vv, 2) if kk == "spend" else vv for kk, vv in v.items()}}
            for k, v in sorted(by_platform.items())
        ],
        "provenance": _provenance(
            db, SourceType.PAID_MEDIA, property_ids, min(dates), max(dates), today
        ),
    }


def _crm_section(db, property_ids, start, end, today):
    q = _scoped(
        db.query(CRMLead).filter(
            CRMLead.first_contact_date >= start, CRMLead.first_contact_date <= end
        ),
        CRMLead,
        property_ids,
    )
    rows = q.all()
    if not rows:
        return None
    funnel = {"lead": 0, "tour": 0, "application": 0, "lease": 0, "lost": 0}
    for r in rows:
        funnel[r.status.value] += 1
    dates = [r.first_contact_date for r in rows]
    return {
        "total_leads": len(rows),
        "funnel": funnel,
        "provenance": _provenance(
            db, SourceType.CRM, property_ids, min(dates), max(dates), today
        ),
    }


def build_dashboard(
    db: Session,
    property_id: int | None,
    days: int,
    today: date | None = None,
    company_id: int | None = None,
    unassigned: bool = False,
) -> dict:
    today = today or date.today()
    property_ids = _resolve_scope(db, property_id, company_id, unassigned)
    anchor = _anchor_date(db, property_ids) or today
    start = anchor - timedelta(days=days - 1)

    # Local import: reporting_events imports helpers from this module, so a
    # top-level import here would be circular.
    from app.services.reporting_events import build_events_section

    return {
        "window": {
            "days": days,
            "start": start.isoformat(),
            "end": anchor.isoformat(),
            "anchored_to_latest_data": anchor != today,
        },
        "ga4": _ga4_section(db, property_ids, start, anchor, today),
        "events": build_events_section(db, property_ids, start, anchor, today),
        "gsc": _gsc_section(db, property_ids, start, anchor, today),
        "gbp": _gbp_section(db, property_ids, start, anchor, today),
        "paid": _paid_section(db, property_ids, start, anchor, today),
        "crm": _crm_section(db, property_ids, start, anchor, today),
    }
