"""Monthly Strategic Briefing (Phase 17A).

The synthesis layer: for one property and one calendar month, it composes an
executive briefing from the modules Beacon already runs. It does NOT re-analyze
anything - it reads build_executive_report (SEO/GA4/AI-visibility/content/
opportunities over the month window), Review Intelligence, and source_status,
then editorializes.

Design commitments (agreed for 17A):
- No opaque composite health number. Each module gets an EXPLAINABLE status with
  its own rule and one-sentence reason; overall health is reported as a COUNT
  of healthy modules, not a synthesized index.
- Adaptive: a module with no data reports "not enough data"; an unconnected
  source (CRM, paid, competitors) reports "not connected" with a call to action,
  never an empty slot or a fabricated section.
- Every status and KPI traces to the module it came from (a details link).
- Forecast, cross-system causal chains, and the strategist synthesis are later
  sub-phases; this phase is the honest core.
"""

import calendar
from datetime import date

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import GA4SessionsDaily, GSCPerformanceDaily, Property
from app.services.reporting import DataState
from app.services.reporting_executive import build_executive_report
from app.services.review_intelligence import analyze_property_reviews

# Explainable status bands. A module maps its signal to one of these; nothing
# here is a hidden score.
EXCELLENT = "excellent"
GOOD = "good"
FAIR = "fair"
NEEDS_ATTENTION = "needs_attention"
NOT_ENOUGH_DATA = "not_enough_data"
NOT_CONNECTED = "not_connected"

STATUS_LABELS = {
    EXCELLENT: "Excellent",
    GOOD: "Good",
    FAIR: "Fair",
    NEEDS_ATTENTION: "Needs attention",
    NOT_ENOUGH_DATA: "Not enough data",
    NOT_CONNECTED: "Not connected",
}

# Statuses that count toward "modules healthy".
_HEALTHY = {EXCELLENT, GOOD}


def _band(value: float) -> str:
    """Shared 0-100 band. Used by any module that has a real 0-100 score."""
    if value >= 85:
        return EXCELLENT
    if value >= 70:
        return GOOD
    if value >= 55:
        return FAIR
    return NEEDS_ATTENTION


def _trend_of(card: dict | None) -> str | None:
    cmp = (card or {}).get("comparison")
    return cmp["direction"] if cmp else None


# --- month windows -----------------------------------------------------------


def _month_bounds(year: int, month: int) -> tuple[date, date]:
    last = calendar.monthrange(year, month)[1]
    return date(year, month, 1), date(year, month, last)


def _prev_month(year: int, month: int) -> tuple[int, int]:
    return (year - 1, 12) if month == 1 else (year, month - 1)


def _latest_data_month(db: Session, property_id: int, today: date) -> tuple[int, int]:
    """The default briefing month. Prefer the newest Search Console month
    (Search Console is the laggard, so its newest month is the latest one with a
    complete SEO picture); fall back to GA4, then today. This avoids defaulting
    to a partial current month that would read as 'not enough data'."""
    gsc = (
        db.query(func.max(GSCPerformanceDaily.date))
        .filter(GSCPerformanceDaily.property_id == property_id)
        .scalar()
    )
    if gsc:
        return gsc.year, gsc.month
    ga4 = (
        db.query(func.max(GA4SessionsDaily.date))
        .filter(GA4SessionsDaily.property_id == property_id)
        .scalar()
    )
    d = ga4 or today
    return d.year, d.month


# --- per-module health -------------------------------------------------------


def _module(key, label, status, reason, details_href, evidence=None):
    return {
        "key": key,
        "label": label,
        "status": status,
        "status_label": STATUS_LABELS[status],
        "reason": reason,
        "details_href": details_href,
        "evidence": evidence or [],
        "healthy": status in _HEALTHY,
    }


def _seo_health(cards: dict) -> dict:
    clicks = cards.get("organic_clicks")
    if clicks is None or clicks.get("state") != DataState.COMPLETE.value:
        return _module("seo", "SEO", NOT_ENOUGH_DATA,
                       "No Search Console data for this month yet.", "/reports/seo")
    cmp = clicks.get("comparison")
    val = clicks.get("value")
    if cmp and cmp["change"] is not None:
        if cmp["direction"] == "up":
            status = GOOD
            reason = f"Organic clicks rose to {val} this month."
        elif cmp["direction"] == "down":
            status = NEEDS_ATTENTION
            reason = f"Organic clicks fell to {val} this month."
        else:
            status = FAIR
            reason = f"Organic clicks held at {val} this month."
    else:
        status = FAIR
        reason = f"{val} organic clicks this month; no comparable prior period."
    return _module("seo", "SEO", status, reason, "/reports/seo",
                   evidence=["Search Console: organic clicks"])


def _ai_visibility_health(cards: dict) -> dict:
    geo = cards.get("ai_mention_rate")
    state = (geo or {}).get("state")
    if state == DataState.NOT_CONFIGURED.value or geo is None:
        return _module("ai_visibility", "AI Visibility", NOT_ENOUGH_DATA,
                       "No AI Visibility queries have been run yet.", "/ai-visibility")
    if state == DataState.INSUFFICIENT_SAMPLE.value:
        return _module("ai_visibility", "AI Visibility", NOT_ENOUGH_DATA,
                       "Too few tested queries to report a mention rate.", "/ai-visibility")
    rate = geo.get("value") or 0
    status = _band(rate * 100)
    return _module("ai_visibility", "AI Visibility", status,
                   f"Mentioned in {round(rate * 100)}% of tested AI answers.",
                   "/ai-visibility", evidence=["AI Visibility: mention rate"])


def _content_health(cards: dict) -> dict:
    c = cards.get("content_score")
    if c is None or c.get("value") is None:
        return _module("content", "Content", NOT_ENOUGH_DATA,
                       "No website content ingested for this property.", "/content-intelligence")
    status = _band(c["value"])
    return _module("content", "Content", status,
                   f"Content Intelligence score {c['value']}.",
                   "/content-intelligence", evidence=["Content Intelligence score"])


def _reviews_health(rv: dict) -> dict:
    if not rv.get("has_reviews"):
        return _module("reviews", "Reviews", NOT_CONNECTED,
                       "No reviews connected. Import reviews to track sentiment.",
                       "/review-intelligence")
    score = rv.get("score") or {}
    avg = rv.get("overview", {}).get("average_rating")
    if score.get("value") is None:
        return _module("reviews", "Reviews", NOT_ENOUGH_DATA,
                       "Not enough reviews to assess sentiment health.", "/review-intelligence")
    status = _band(score["value"])
    reason = (
        f"Average rating {avg}/5 across {rv['overview']['total_reviews']} reviews."
        if avg is not None
        else f"Review health score {round(score['value'])}."
    )
    return _module("reviews", "Reviews", status, reason, "/review-intelligence",
                   evidence=["Review Intelligence"])


def _website_health(db, property_id, window) -> dict:
    rows = (
        db.query(GA4SessionsDaily)
        .filter(
            GA4SessionsDaily.property_id == property_id,
            GA4SessionsDaily.date >= window[0],
            GA4SessionsDaily.date <= window[1],
        )
        .all()
    )
    if not rows:
        return _module("website", "Website", NOT_CONNECTED,
                       "No GA4 data connected for this month.", "/")
    sessions = sum(r.sessions for r in rows)
    engaged = sum(r.engaged_sessions for r in rows)
    if not sessions:
        return _module("website", "Website", NOT_ENOUGH_DATA,
                       "GA4 rows present but no sessions in this month.", "/")
    rate = engaged / sessions
    status = _band(rate * 100)
    return _module("website", "Website", status,
                   f"{round(rate * 100)}% of {sessions} sessions were engaged.",
                   "/", evidence=["GA4: engaged sessions"])


# --- This Month's Story (17B) --------------------------------------------------
# Deterministic wins / risks / trends derived from what the modules already
# computed. Every item names its evidence and links to its module. Items exist
# only when the underlying signal does; empty groups are reported honestly.

MAX_STORY_ITEMS = 5


def _item(text, evidence, label, href, module):
    return {
        "text": text,
        "evidence": evidence,
        "link": {"label": label, "href": href},
        "source_module": module,
    }


def _story(cards: dict, seo: dict, review: dict, av_trend_points: list) -> dict:
    wins: list = []
    risks: list = []
    trends: list = []

    # Metric movements from the executive cards (observed change, no causation).
    metric_names = {
        "organic_clicks": "Organic clicks",
        "organic_sessions": "Organic sessions",
        "ai_referral_sessions": "AI referral sessions",
    }
    for key, name in metric_names.items():
        c = cards.get(key)
        cmp = (c or {}).get("comparison")
        if not cmp or cmp.get("change") in (None, 0):
            continue
        text = (
            f"{name} moved from {cmp['previous']} to {cmp['current']} versus the "
            "prior month."
        )
        target = wins if (cmp["direction"] == "up") else risks
        target.append(_item(text, [f"{c['source']}: {cmp['previous']} to {cmp['current']}"],
                            "SEO Performance", "/reports/seo", "seo"))

    # Search movers: top gaining and declining imported queries.
    movers = seo.get("movers", {})
    for g in (movers.get("gains") or [])[:2]:
        pos = (
            f", position {g['previous_position']} to {g['current_position']}"
            if g.get("current_position") is not None and g.get("previous_position") is not None
            else ""
        )
        wins.append(_item(
            f"\"{g['query']}\" gained {g['click_change']} clicks{pos}.",
            [f"Search Console: {g['previous_clicks']} to {g['current_clicks']} clicks"],
            "SEO Performance", "/reports/seo", "seo",
        ))
    for d in (movers.get("losses") or [])[:2]:
        risks.append(_item(
            f"\"{d['query']}\" lost {abs(d['click_change'])} clicks versus the prior month.",
            [f"Search Console: {d['previous_clicks']} to {d['current_clicks']} clicks"],
            "SEO Performance", "/reports/seo", "seo",
        ))

    # Review trends (only when the analyzer deemed them determinable).
    rmetrics = (review.get("trends") or {}).get("metrics", {})
    ar = rmetrics.get("average_rating")
    if ar and ar.get("recent") is not None and ar.get("prior") is not None:
        if ar["recent"] > ar["prior"]:
            wins.append(_item(
                f"Recent review rating rose to {ar['recent']}/5 from {ar['prior']}/5.",
                ["Review Intelligence: recent vs prior window"],
                "Review IQ", "/review-intelligence", "reviews",
            ))
        elif ar["recent"] < ar["prior"]:
            risks.append(_item(
                f"Recent review rating slipped to {ar['recent']}/5 from {ar['prior']}/5.",
                ["Review Intelligence: recent vs prior window"],
                "Review IQ", "/review-intelligence", "reviews",
            ))
    neg = rmetrics.get("negative_reviews")
    if neg and neg.get("recent") is not None and neg.get("prior") is not None \
            and neg["recent"] > neg["prior"]:
        trends.append(_item(
            f"Negative reviews rising: {neg['recent']} recent vs {neg['prior']} prior.",
            ["Review Intelligence: negative review counts"],
            "Review IQ", "/review-intelligence", "reviews",
        ))

    # Complaint themes with severity are emerging patterns worth watching.
    for opp in (review.get("opportunities") or [])[:2]:
        label = opp.get("theme_label") or opp.get("theme") or opp.get("title")
        if label:
            trends.append(_item(
                f"Residents keep raising {str(label).lower()} in reviews.",
                [f"Review Intelligence: complaint severity {opp.get('severity', 'n/a')}"],
                "Review IQ", "/review-intelligence", "reviews",
            ))

    # AI visibility trajectory across sufficient-scored captures.
    scored = [p for p in av_trend_points if p.get("score") is not None]
    if len(scored) >= 2:
        first, last = scored[0], scored[-1]
        if last["score"] > first["score"]:
            wins.append(_item(
                f"AI visibility score rose from {first['score']} to {last['score']} across runs.",
                [f"AI Visibility score history ({len(scored)} scored runs)"],
                "AI Visibility", "/ai-visibility", "ai_visibility",
            ))
        elif last["score"] < first["score"]:
            risks.append(_item(
                f"AI visibility score fell from {first['score']} to {last['score']} across runs.",
                [f"AI Visibility score history ({len(scored)} scored runs)"],
                "AI Visibility", "/ai-visibility", "ai_visibility",
            ))

    return {
        "wins": wins[:MAX_STORY_ITEMS],
        "risks": risks[:MAX_STORY_ITEMS],
        "trends": trends[:MAX_STORY_ITEMS],
        "note": (
            "Observed movements from Beacon's stored data. Movements are not "
            "causal claims; each item links to its source module."
        ),
    }


# --- Intelligence cards (17B) --------------------------------------------------


def _intel_cards(cards: dict, seo: dict, review: dict, content_analysis: dict) -> list[dict]:
    """One compact card per module: what happened, the biggest opportunity, and
    where to look. States are honest; nothing renders as a fake zero."""
    out = []

    clicks = cards.get("organic_clicks") or {}
    movers = seo.get("movers", {})
    gains = len(movers.get("gains") or [])
    declines = len(movers.get("declines") or [])
    if clicks.get("state") == DataState.COMPLETE.value:
        what = f"{clicks['value']} organic clicks this month."
        if gains or declines:
            what += f" {gains} quer{'y' if gains == 1 else 'ies'} gained, {declines} declined."
        quad = seo.get("quadrant", {})
        strike = (quad.get("highlights") or {}).get("striking_distance") or 0
        opp = (
            f"{strike} queries rank in positions 8 to 20, within reach of page one."
            if strike else "No striking-distance queries flagged this month."
        )
        out.append({"key": "seo", "label": "SEO", "state": "ok",
                    "what_happened": what, "biggest_opportunity": opp,
                    "href": "/reports/seo"})
    else:
        out.append({"key": "seo", "label": "SEO", "state": "no_data",
                    "what_happened": "No Search Console data for this month.",
                    "biggest_opportunity": None, "href": "/reports/seo"})

    geo = cards.get("ai_mention_rate") or {}
    if geo.get("state") == DataState.COMPLETE.value:
        s = geo.get("sample") or {}
        out.append({"key": "ai_visibility", "label": "AI Visibility", "state": "ok",
                    "what_happened": f"Mentioned in {s.get('numerator')} of {s.get('denominator')} tested AI answers.",
                    "biggest_opportunity": "Review which tested queries omit the property.",
                    "href": "/reports/geo"})
    else:
        out.append({"key": "ai_visibility", "label": "AI Visibility", "state": "no_data",
                    "what_happened": geo.get("detail") or "Not enough tested queries for a rate.",
                    "biggest_opportunity": "Run the standing prompt set to clear the sample gate.",
                    "href": "/ai-visibility"})

    ci_score = cards.get("content_score") or {}
    if ci_score.get("value") is not None:
        top_ci = (content_analysis.get("opportunities") or [{}])[0]
        out.append({"key": "content", "label": "Content", "state": "ok",
                    "what_happened": f"Content Intelligence score {ci_score['value']}.",
                    "biggest_opportunity": top_ci.get("title"),
                    "href": "/content-intelligence"})
    else:
        out.append({"key": "content", "label": "Content", "state": "no_data",
                    "what_happened": "No website content ingested.",
                    "biggest_opportunity": "Add website content to enable analysis.",
                    "href": "/content-intelligence"})

    if review.get("has_reviews"):
        ov = review.get("overview", {})
        top_rv = (review.get("opportunities") or [{}])[0]
        rating = ov.get("average_rating")
        out.append({"key": "reviews", "label": "Reviews", "state": "ok",
                    "what_happened": (
                        f"{ov.get('total_reviews')} reviews"
                        + (f", average {rating}/5." if rating is not None else ".")
                    ),
                    "biggest_opportunity": top_rv.get("title") or top_rv.get("theme_label"),
                    "href": "/review-intelligence"})
    else:
        out.append({"key": "reviews", "label": "Reviews", "state": "not_connected",
                    "what_happened": "No reviews connected.",
                    "biggest_opportunity": "Import reviews to track sentiment and themes.",
                    "href": "/review-intelligence"})

    return out


# --- adaptive (unconnected) sections -----------------------------------------


def _adaptive_sections(sources: dict) -> list[dict]:
    """Sections that appear only as connect-me cards until their source exists.
    Kept honest: no fabricated leasing/paid/competitor content."""
    by_key = {s["key"]: s for s in sources.get("sources", [])}
    cards = []
    # Leasing performance needs a CRM, which Beacon does not yet ingest.
    cards.append({
        "key": "leasing",
        "label": "Leasing Performance",
        "connected": False,
        "message": "Connect your CRM to unlock leasing performance, marketing "
                   "attribution, lead-to-lease reporting, and occupancy insights.",
        "cta": "Connect CRM",
    })
    # Competitor share needs operator-named competitors.
    cards.append({
        "key": "competitors",
        "label": "Competitor Intelligence",
        "connected": False,
        "message": "Add competitors on the Competitor IQ page to compare share "
                   "of tested AI answers. Beacon never guesses competitors.",
        "cta": "Add competitors",
    })
    return cards


# --- compose -----------------------------------------------------------------


def compose_briefing(
    db: Session,
    property_id: int,
    year: int,
    month: int,
    today: date | None = None,
) -> dict:
    today = today or date.today()
    prop = db.get(Property, property_id)
    if prop is None:
        raise ValueError("Property not found.")

    window = _month_bounds(year, month)
    py, pm = _prev_month(year, month)
    prev_window = _month_bounds(py, pm)
    days = (window[1] - window[0]).days + 1

    exec_report = build_executive_report(
        db, property_id, days, want_compare=True, today=today,
        window=window, prev_window=prev_window,
    )
    cards_by_key = {c["key"]: c for c in exec_report.get("cards", [])}

    from app.models import AIVisibilityScoreHistory
    from app.services.content_intelligence import analyze_property
    from app.services.reporting import source_status
    from app.services.reporting_seo import build_seo_report

    sources = source_status(db, property_id, today=today)
    # Month-scoped SEO report for movers/quadrant story items and the SEO card.
    seo = build_seo_report(
        db, property_id, days, want_compare=True, today=today,
        window=window, prev_window=prev_window,
    )
    try:
        review = analyze_property_reviews(db, property_id, today=today)
    except Exception:
        review = {"has_reviews": False}
    try:
        content_analysis = analyze_property(db, property_id, today=today)
    except Exception:
        content_analysis = {"has_content": False}
    av_points = [
        {"score": h.score, "captured_at": h.captured_at.date().isoformat()}
        for h in db.query(AIVisibilityScoreHistory)
        .filter(AIVisibilityScoreHistory.property_id == property_id)
        .order_by(AIVisibilityScoreHistory.captured_at)
        .all()
    ]

    modules = [
        _seo_health(cards_by_key),
        _ai_visibility_health(cards_by_key),
        _content_health(cards_by_key),
        _reviews_health(review),
        _website_health(db, property_id, window),
    ]
    healthy = sum(1 for m in modules if m["healthy"])
    assessable = [m for m in modules if m["status"] not in (NOT_CONNECTED, NOT_ENOUGH_DATA)]

    # KPI snapshot: reuse the executive cards (value + prior + change), the
    # ones a manager scans first.
    kpi_keys = [
        "organic_clicks", "ai_referral_sessions", "ai_mention_rate",
        "content_score", "actionable_opportunities",
    ]
    kpis = [cards_by_key[k] for k in kpi_keys if k in cards_by_key]

    month_name = f"{calendar.month_name[month]} {year}"
    prev_name = f"{calendar.month_name[pm]} {py}"

    return {
        "property_id": property_id,
        "property_name": prop.name,
        "period": {
            "label": month_name,
            "start": window[0].isoformat(),
            "end": window[1].isoformat(),
            "year": year,
            "month": month,
        },
        "comparison_period": {
            "label": prev_name,
            "start": prev_window[0].isoformat(),
            "end": prev_window[1].isoformat(),
        },
        "health": {
            "modules": modules,
            # A COUNT, not an opaque index. Only modules with data are counted.
            "healthy_count": healthy,
            "assessable_count": len(assessable),
            "summary": (
                f"{healthy} of {len(assessable)} assessable modules are healthy."
                if assessable
                else "Not enough connected data to assess module health yet."
            ),
        },
        "executive_summary": exec_report.get("narrative", []),
        "kpis": kpis,
        "story": _story(cards_by_key, seo, review, av_points),
        "intelligence_cards": _intel_cards(cards_by_key, seo, review, content_analysis),
        "top_priorities": exec_report.get("top_actions", [])[:5],
        "adaptive_sections": _adaptive_sections(sources),
        "data_sources": sources,
        "generated_on": today.isoformat(),
    }
