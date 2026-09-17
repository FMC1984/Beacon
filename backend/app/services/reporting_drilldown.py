"""Drilldown for the Reports section: any summary card to the rows behind it.

Each card key maps to one resolver that returns the same rows the card was
computed from, over the same window, grouped the way a person would want to
inspect them (queries for Search Console, sources for GA4, components for a
score). One registry, so a card can never claim a drilldown it does not
have: unknown keys return `available: False` with a stated reason rather
than an empty list that implies "nothing happened".

Every resolver reports the totals it saw alongside the rows, so the drawer
can show "these 25 rows are 25 of 214" and the summary number can be
checked against its own evidence.
"""

from collections import defaultdict
from datetime import date, timedelta

from sqlalchemy.orm import Session

from app.models import GA4SessionsDaily, GSCPerformanceDaily, Property
from app.services.reporting import DataState, previous_window

MAX_ROWS = 50


def _window(days: int, today: date) -> tuple[date, date]:
    return today - timedelta(days=days - 1), today


def _gsc(db: Session, property_id: int, start: date, end: date):
    return db.query(GSCPerformanceDaily).filter(
        GSCPerformanceDaily.property_id == property_id,
        GSCPerformanceDaily.date >= start, GSCPerformanceDaily.date <= end,
    ).all()


def _ga4(db: Session, property_id: int, start: date, end: date, organic_only: bool = False, ai_only: bool = False):
    q = db.query(GA4SessionsDaily).filter(
        GA4SessionsDaily.property_id == property_id,
        GA4SessionsDaily.date >= start, GA4SessionsDaily.date <= end,
    )
    if organic_only:
        q = q.filter(GA4SessionsDaily.session_medium == "organic")
    if ai_only:
        q = q.filter(GA4SessionsDaily.is_ai_referral.is_(True))
    return q.all()


# --- Search Console resolvers ------------------------------------------------


def _gsc_by_query(db, property_id, start, end, sort_key: str, higher_is_better=True):
    rows = _gsc(db, property_id, start, end)
    agg: dict[str, dict] = defaultdict(lambda: {"clicks": 0, "impressions": 0, "pos_w": 0.0})
    for r in rows:
        a = agg[r.query or "(not set)"]
        a["clicks"] += r.clicks
        a["impressions"] += r.impressions
        a["pos_w"] += r.position * r.impressions
    items = []
    for query, a in agg.items():
        items.append({
            "query": query, "clicks": a["clicks"], "impressions": a["impressions"],
            "ctr": round(a["clicks"] / a["impressions"], 4) if a["impressions"] else None,
            "position": round(a["pos_w"] / a["impressions"], 1) if a["impressions"] else None,
        })
    reverse = not (sort_key == "position")
    items.sort(key=lambda i: (i[sort_key] is None, -(i[sort_key] or 0) if reverse else (i[sort_key] or 0)))
    total_clicks = sum(i["clicks"] for i in items)
    total_imps = sum(i["impressions"] for i in items)
    return {
        "columns": ["query", "clicks", "impressions", "ctr", "position"],
        "group": "Search Console query",
        "totals": {"clicks": total_clicks, "impressions": total_imps, "queries": len(items),
                   "ctr": round(total_clicks / total_imps, 4) if total_imps else None},
        "items": items[:MAX_ROWS],
        "total_rows": len(items),
    }


# --- GA4 resolvers -----------------------------------------------------------


def _ga4_by_source(db, property_id, start, end, organic_only=False, ai_only=False, metric="sessions"):
    rows = _ga4(db, property_id, start, end, organic_only=organic_only, ai_only=ai_only)
    agg: dict[tuple, dict] = defaultdict(lambda: {"sessions": 0, "engaged": 0, "key_events": 0, "users": 0})
    for r in rows:
        key = (r.session_source, r.session_medium, r.ai_platform)
        a = agg[key]
        a["sessions"] += r.sessions
        a["engaged"] += r.engaged_sessions
        a["key_events"] += r.key_events
        a["users"] += r.total_users
    items = [
        {"source": s, "medium": m, "ai_platform": p, **a,
         "engagement_rate": round(a["engaged"] / a["sessions"], 4) if a["sessions"] else None}
        for (s, m, p), a in agg.items()
    ]
    items.sort(key=lambda i: -i[metric])
    return {
        "columns": ["source", "medium", "sessions", "engaged", "key_events", "engagement_rate"],
        "group": "GA4 source / medium",
        "totals": {"sessions": sum(i["sessions"] for i in items), "engaged": sum(i["engaged"] for i in items),
                   "key_events": sum(i["key_events"] for i in items), "sources": len(items)},
        "items": items[:MAX_ROWS],
        "total_rows": len(items),
    }


def _ga4_by_landing(db, property_id, start, end, ai_only=False):
    rows = _ga4(db, property_id, start, end, ai_only=ai_only)
    agg: dict[str, dict] = defaultdict(lambda: {"sessions": 0, "key_events": 0})
    for r in rows:
        a = agg[r.landing_page or "(not set)"]
        a["sessions"] += r.sessions
        a["key_events"] += r.key_events
    items = [{"landing_page": k, **a} for k, a in agg.items()]
    items.sort(key=lambda i: -i["sessions"])
    return {
        "columns": ["landing_page", "sessions", "key_events"],
        "group": "Landing page",
        "totals": {"sessions": sum(i["sessions"] for i in items), "pages": len(items)},
        "items": items[:MAX_ROWS],
        "total_rows": len(items),
    }


def _ga4_by_city(db, property_id, start, end):
    rows = _ga4(db, property_id, start, end)
    agg: dict[tuple, dict] = defaultdict(lambda: {"sessions": 0, "ai_sessions": 0, "engaged": 0})
    for r in rows:
        a = agg[(r.city or "Unknown", r.region or "")]
        a["sessions"] += r.sessions
        a["engaged"] += r.engaged_sessions
        if r.is_ai_referral:
            a["ai_sessions"] += r.sessions
    items = [{"city": c, "region": reg, **a} for (c, reg), a in agg.items()]
    items.sort(key=lambda i: -i["sessions"])
    return {
        "columns": ["city", "region", "sessions", "ai_sessions", "engaged"],
        "group": "City",
        "totals": {"sessions": sum(i["sessions"] for i in items), "cities": len(items)},
        "items": items[:MAX_ROWS],
        "total_rows": len(items),
    }


# --- score resolvers ---------------------------------------------------------


def _content_score_components(db, property_id, start, end):
    from app.services.content_intelligence import analyze_property

    a = analyze_property(db, property_id, today=end)
    comps = a.get("score", {}).get("breakdown", [])
    items = [{"component": c["component"].replace("_", " "), "score": c["score"], "weight": c["weight"],
              "explanation": c["explanation"]} for c in comps]
    return {
        "columns": ["component", "score", "weight", "explanation"],
        "group": "Score component",
        "totals": {"score": a.get("score", {}).get("value"), "components": len(items)},
        "items": items, "total_rows": len(items),
    }


def _opportunities(db, property_id, start, end):
    from app.services.opportunity_engine import build_opportunities

    o = build_opportunities(db, property_id, today=end)
    items = [{"priority": x["priority"], "title": x["title"], "source": x["source_label"], "state": x["state"],
              "impact": x["impact"], "effort": x["effort"], "reason": x["reason"]}
             for x in o.get("opportunities", [])]
    return {
        "columns": ["priority", "title", "source", "state", "impact", "effort"],
        "group": "Opportunity",
        "totals": {"actionable": len(items), "suppressed": len(o.get("suppressed", [])),
                   "insufficient": len(o.get("insufficient", []))},
        "items": items[:MAX_ROWS], "total_rows": len(items),
    }


def _ai_visibility(db, property_id, start, end, metric):
    """Observatory metrics drill into observations through the Observatory's
    own evidence endpoint; this returns a pointer plus the top rows inline."""
    from app.services.observatory.drilldown import evidence

    days = (end - start).days + 1
    e = evidence(db, property_id, metric, days=days, today=end, limit=MAX_ROWS)
    items = [{"observed_at": i["observed_at"][:10], "prompt": i["prompt"], "platform": i["platform"],
              "mention_rank": i["mention_rank"], "cited": i["cited"], "sentiment": i["sentiment"],
              "response_id": i["response_id"]} for i in e["items"]]
    return {
        "columns": ["observed_at", "prompt", "platform", "mention_rank", "cited", "sentiment"],
        "group": "Monitored AI answer",
        "totals": {"counting": e["numerator"], "eligible": e["denominator"]},
        "items": items, "total_rows": e["total"],
        "observatory_metric": metric,
    }


# --- registry ----------------------------------------------------------------

RESOLVERS = {
    # Search Console
    "organic_clicks": ("Search Console", lambda db, p, s, e: _gsc_by_query(db, p, s, e, "clicks")),
    "organic_impressions": ("Search Console", lambda db, p, s, e: _gsc_by_query(db, p, s, e, "impressions")),
    "ctr": ("Search Console", lambda db, p, s, e: _gsc_by_query(db, p, s, e, "clicks")),
    "avg_position": ("Search Console", lambda db, p, s, e: _gsc_by_query(db, p, s, e, "position")),
    # GA4
    "organic_sessions": ("GA4", lambda db, p, s, e: _ga4_by_source(db, p, s, e, organic_only=True)),
    "organic_engaged_sessions": ("GA4", lambda db, p, s, e: _ga4_by_source(db, p, s, e, organic_only=True, metric="engaged")),
    "organic_key_events": ("GA4", lambda db, p, s, e: _ga4_by_source(db, p, s, e, organic_only=True, metric="key_events")),
    "organic_conversion_rate": ("GA4", lambda db, p, s, e: _ga4_by_source(db, p, s, e, organic_only=True, metric="key_events")),
    "ai_referral_sessions": ("GA4", lambda db, p, s, e: _ga4_by_source(db, p, s, e, ai_only=True)),
    "ai_share": ("GA4", lambda db, p, s, e: _ga4_by_source(db, p, s, e)),
    "total_sessions": ("GA4", lambda db, p, s, e: _ga4_by_source(db, p, s, e)),
    "located_share": ("GA4", _ga4_by_city),
    "cities_represented": ("GA4", _ga4_by_city),
    "top_city": ("GA4", _ga4_by_city),
    "ai_landing_pages": ("GA4", lambda db, p, s, e: _ga4_by_landing(db, p, s, e, ai_only=True)),
    # Scores and engines
    "content_score": ("Content Analysis", _content_score_components),
    "actionable_opportunities": ("Opportunity Engine", _opportunities),
    # AI Visibility (observatory-backed)
    "ai_mention_rate": ("AI Visibility", lambda db, p, s, e: _ai_visibility(db, p, s, e, "ai_visibility")),
    "mention_count": ("AI Visibility", lambda db, p, s, e: _ai_visibility(db, p, s, e, "ai_visibility")),
    "owned_domain_citations": ("AI Visibility", lambda db, p, s, e: _ai_visibility(db, p, s, e, "citation_rate")),
    "queries_completed": ("AI Visibility", lambda db, p, s, e: _ai_visibility(db, p, s, e, "all")),
    "share_of_voice": ("AI Share of Voice", lambda db, p, s, e: _ai_visibility(db, p, s, e, "share_of_voice")),
}


def report_drilldown(db: Session, property_id: int, card: str, days: int = 30, today: date | None = None,
                     compare_previous: bool = False) -> dict:
    prop = db.get(Property, property_id)
    if prop is None:
        raise ValueError("Property not found.")
    today = today or date.today()
    start, end = _window(days, today)
    if card not in RESOLVERS:
        return {
            "available": False, "card": card, "property_id": property_id,
            "reason": "This figure has no row-level drilldown yet. The number is still real; it just cannot be "
                      "expanded here.",
        }
    source, resolve = RESOLVERS[card]
    current = resolve(db, property_id, start, end)
    out = {
        "available": True, "card": card, "property_id": property_id, "property_name": prop.name,
        "source": source,
        "window": {"start": start.isoformat(), "end": end.isoformat(), "days": days},
        "state": DataState.COMPLETE.value if current["total_rows"] else DataState.EMPTY.value,
        **current,
    }
    if compare_previous:
        p_start, p_end = previous_window(start, end)
        out["previous"] = {"window": {"start": p_start.isoformat(), "end": p_end.isoformat()},
                           **resolve(db, property_id, p_start, p_end)}
    return out
