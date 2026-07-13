"""Audience geography report (Phase 16G).

Answers "where are our users" from GA4's City / Region dimensions. It composes,
never recomputes: sessions and users come straight from stored GA4 rows, the
AI-referral split reuses the ``is_ai_referral`` fact stamped at ingest, and the
window anchors to the latest GA4 data exactly as the SEO report does.

Two truth rules specific to geography:
- A visitor whose city GA4 could not resolve is counted honestly under
  "Unknown"; the report always states the located share so partial geography is
  never mistaken for the whole audience.
- When GA4 rows exist but none carry a city (older exports had no City
  dimension), the report says so and asks for a re-export rather than showing an
  empty map as if nobody had a location.

Every AI figure carries the fixed undercount disclosure (constants.py).
"""

from datetime import date, timedelta

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.constants import AI_TRAFFIC_DISCLOSURE
from app.models import Company, GA4SessionsDaily, Property
from app.services.metrics import _resolve_scope, _scoped

UNKNOWN_CITY = "Unknown"
# Cap the on-screen city table; the CSV export carries the full list.
DEFAULT_CITY_LIMIT = 25

GEOGRAPHY_NOTE = (
    "City and region come from GA4's approximate geolocation and are only as "
    "complete as the uploaded export. Sessions GA4 could not place appear under "
    "Unknown."
)


def _scope_label(
    db: Session, property_id: int | None, company_id: int | None, unassigned: bool
) -> str:
    if property_id is not None:
        p = db.get(Property, property_id)
        return p.name if p else "Unknown property"
    if unassigned:
        return "Unassigned properties"
    if company_id is not None:
        c = db.get(Company, company_id)
        return c.name if c else "Unknown company"
    return "All properties"


def _anchor(db: Session, property_ids) -> date | None:
    """Newest GA4 date in scope, so a report reads the latest data present
    rather than a today-relative window that may be empty (matches the SEO
    report's anchoring)."""
    return _scoped(
        db.query(func.max(GA4SessionsDaily.date)), GA4SessionsDaily, property_ids
    ).scalar()


def _share(part: int, whole: int) -> float | None:
    return round(part / whole, 4) if whole else None


def aggregate_geography(rows) -> dict:
    """Fold GA4 rows into city and region rollups plus totals. Pure (no DB) so
    both the Audience report and the Executive panel share one definition.

    City is grouped with its region so same-named cities in different regions
    stay distinct. Rows GA4 could not place (city NULL) collapse into a single
    Unknown bucket. Region rollups only count rows with a known region.
    """
    cities: dict[tuple[str, str | None], dict] = {}
    regions: dict[str, dict] = {}
    total_sessions = total_users = ai_sessions = engaged = key_events = 0
    located_sessions = 0

    for r in rows:
        total_sessions += r.sessions
        total_users += r.total_users
        engaged += r.engaged_sessions
        key_events += r.key_events
        if r.is_ai_referral:
            ai_sessions += r.sessions

        if r.city:
            located_sessions += r.sessions
            ckey = (r.city, r.region)
        else:
            ckey = (UNKNOWN_CITY, None)
        c = cities.setdefault(
            ckey,
            {
                "city": ckey[0],
                "region": ckey[1],
                "sessions": 0,
                "users": 0,
                "engaged_sessions": 0,
                "key_events": 0,
                "ai_sessions": 0,
            },
        )
        c["sessions"] += r.sessions
        c["users"] += r.total_users
        c["engaged_sessions"] += r.engaged_sessions
        c["key_events"] += r.key_events
        if r.is_ai_referral:
            c["ai_sessions"] += r.sessions

        if r.region:
            rg = regions.setdefault(
                r.region, {"region": r.region, "sessions": 0, "users": 0}
            )
            rg["sessions"] += r.sessions
            rg["users"] += r.total_users

    for c in cities.values():
        c["engagement_rate"] = _share(c["engaged_sessions"], c["sessions"])
        c["sessions_share"] = _share(c["sessions"], total_sessions)
        c["ai_share"] = _share(c["ai_sessions"], c["sessions"])
    for rg in regions.values():
        rg["sessions_share"] = _share(rg["sessions"], total_sessions)

    city_list = sorted(
        cities.values(), key=lambda c: (c["city"] == UNKNOWN_CITY, -c["sessions"])
    )
    region_list = sorted(regions.values(), key=lambda r: r["sessions"], reverse=True)
    known_cities = [c for c in city_list if c["city"] != UNKNOWN_CITY]

    return {
        "total_sessions": total_sessions,
        "total_users": total_users,
        "engaged_sessions": engaged,
        "key_events": key_events,
        "ai_sessions": ai_sessions,
        "located_sessions": located_sessions,
        "cities": city_list,
        "known_cities": known_cities,
        "regions": region_list,
    }


def _window_rows(db: Session, property_ids, start: date, end: date):
    return _scoped(
        db.query(GA4SessionsDaily).filter(
            GA4SessionsDaily.date >= start,
            GA4SessionsDaily.date <= end,
        ),
        GA4SessionsDaily,
        property_ids,
    ).all()


def top_cities_for_window(
    db: Session, property_id: int, start: date, end: date, limit: int = 5
) -> dict:
    """Compact top-cities block for the Executive report. Per-property, over the
    Executive report's own window. Returns availability so the panel can render
    an honest 'add the City dimension' state instead of an empty list."""
    rows = _window_rows(db, [property_id], start, end)
    if not rows:
        return {"available": False, "reason": "no_ga4"}
    agg = aggregate_geography(rows)
    if agg["located_sessions"] == 0:
        return {"available": False, "reason": "no_geography"}
    return {
        "available": True,
        "reason": None,
        "located_share": _share(agg["located_sessions"], agg["total_sessions"]),
        "located_sessions": agg["located_sessions"],
        "total_sessions": agg["total_sessions"],
        "cities": [
            {
                "city": c["city"],
                "region": c["region"],
                "sessions": c["sessions"],
                "sessions_share": c["sessions_share"],
            }
            for c in agg["known_cities"][:limit]
        ],
        "disclosure": AI_TRAFFIC_DISCLOSURE,
    }


def build_audience_report(
    db: Session,
    property_id: int | None,
    days: int,
    company_id: int | None = None,
    unassigned: bool = False,
    today: date | None = None,
    city_limit: int = DEFAULT_CITY_LIMIT,
) -> dict:
    """Where the audience is, by city and region, over a scoped window anchored
    to the latest GA4 data. Portfolio, company, unassigned, and single-property
    scopes are all valid: 'where are our users' is a fair question at any scope."""
    today = today or date.today()
    property_ids = _resolve_scope(db, property_id, company_id, unassigned)
    label = _scope_label(db, property_id, company_id, unassigned)

    anchor = _anchor(db, property_ids)
    if anchor is None:
        return {
            "scope_label": label,
            "has_data": False,
            "geography_available": False,
            "message": (
                "No GA4 data has been uploaded for this scope yet. Upload a GA4 "
                "traffic export to see where visitors come from."
            ),
            "generated_on": today.isoformat(),
        }

    window = (anchor - timedelta(days=days - 1), anchor)
    rows = _window_rows(db, property_ids, window[0], window[1])
    agg = aggregate_geography(rows)

    total = agg["total_sessions"]
    located = agg["located_sessions"]
    geography_available = located > 0
    top_city = agg["known_cities"][0] if agg["known_cities"] else None

    cities_full = agg["cities"]
    cities_shown = cities_full[:city_limit]

    summary = {
        "total_sessions": total,
        "total_users": agg["total_users"],
        "ai_sessions": agg["ai_sessions"],
        "ai_share": _share(agg["ai_sessions"], total),
        "located_sessions": located,
        "located_share": _share(located, total),
        "distinct_cities": len(agg["known_cities"]),
        "distinct_regions": len(agg["regions"]),
        "top_city": (
            {
                "city": top_city["city"],
                "region": top_city["region"],
                "sessions": top_city["sessions"],
                "sessions_share": top_city["sessions_share"],
            }
            if top_city
            else None
        ),
    }

    return {
        "scope_label": label,
        "has_data": True,
        "geography_available": geography_available,
        "geography_note": GEOGRAPHY_NOTE,
        "geography_message": (
            None
            if geography_available
            else (
                "GA4 data is present but none of it carries a city. Re-export "
                "your GA4 report with the City (and Region) dimension added, then "
                "re-upload it, to see where visitors come from."
            )
        ),
        "disclosure": AI_TRAFFIC_DISCLOSURE,
        "window": {
            "days": days,
            "start": window[0].isoformat(),
            "end": window[1].isoformat(),
            "anchored_to_latest_data": anchor != today,
        },
        "last_data_date": anchor.isoformat(),
        "summary": summary,
        "cities": cities_shown,
        "cities_shown": len(cities_shown),
        "cities_total": len(cities_full),
        "regions": agg["regions"],
        "generated_on": today.isoformat(),
    }
