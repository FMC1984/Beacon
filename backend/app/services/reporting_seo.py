"""SEO Performance report (Phase 16B).

Composes existing GA4 and Search Console data into the SEO report sections:
summary cards, search trends, ranking distribution, opportunity quadrant,
gains and losses, and landing-page performance. Every section is deterministic
arithmetic over stored rows; classification rules are transparent constants.

Truth rules honored here:
- Query-level sections operate only on rows that carry a query and are always
  labeled as a distribution of imported Search Console queries, never a
  complete rank-tracking database.
- Period comparisons are only offered when both windows have compatible
  coverage (reporting.comparable); otherwise the comparison is null with a
  warning, never a silently wrong percentage.
- Rates carry numerator and denominator. Missing sides of a URL join are
  null, never zero. Caps on table sizes report how many rows were dropped.
- GA4 organic is identified deterministically: session_medium == "organic".
"""

from datetime import date, timedelta

from sqlalchemy import func
from sqlalchemy.orm import Session

from app.models import GA4SessionsDaily, GSCPerformanceDaily, Property
from app.services.ai_query_signals import _canonical_page, _norm_path
from app.services.metrics import (
    FRESHNESS_THRESHOLD_DAYS,
    _resolve_scope,
    _scoped,
)
from app.services.reporting import (
    DataState,
    comparable,
    compare,
    coverage_state,
    previous_window,
    rate,
)
from app.services.semantic.enrichment import enrich_text

# --- Deterministic thresholds (documented in the API payload) ---------------

# A query must have this many impressions in at least one period to appear in
# movers/highlights; below this, movement is noise, not signal.
MIN_QUERY_IMPRESSIONS = 10
# Movement significance: either clicks moved by this much or position did.
MIN_CLICK_CHANGE = 3
MIN_POSITION_CHANGE = 1.0
# Highlight rules for the opportunity quadrant.
HIGH_IMPRESSIONS = 20
LOW_CTR = 0.01
STRIKING_DISTANCE = (8.0, 20.0)
STRONG_POSITION = 5.0
STRONG_RANK_LOW_CTR = 0.02
DECLINE_POSITION_DROP = 3.0
MOVERS_LIMIT = 10
QUADRANT_LIMIT = 100
LANDING_PAGES_LIMIT = 30

RANK_BUCKETS = [
    ("1-3", 3.0),
    ("4-10", 10.0),
    ("11-20", 20.0),
    ("21-50", 50.0),
    ("51+", float("inf")),
]

URL_NORMALIZATION_NOTE = (
    "GA4 landing pages and Search Console pages are joined only through "
    "normalized paths: scheme and host removed, lowercased, query string and "
    "fragment dropped, trailing slash removed. Rows that do not match are "
    "counted, not forced."
)

QUERY_DATA_NOTE = (
    "A distribution of imported Search Console queries. Google omits rare "
    "queries, so this is not a complete rank-tracking database."
)


# --- Shared helpers ----------------------------------------------------------


def _gsc_rows(db, property_ids, start, end):
    return _scoped(
        db.query(GSCPerformanceDaily).filter(
            GSCPerformanceDaily.date >= start, GSCPerformanceDaily.date <= end
        ),
        GSCPerformanceDaily,
        property_ids,
    ).all()


def _ga4_organic_rows(db, property_ids, start, end):
    return _scoped(
        db.query(GA4SessionsDaily).filter(
            GA4SessionsDaily.date >= start,
            GA4SessionsDaily.date <= end,
            func.lower(GA4SessionsDaily.session_medium) == "organic",
        ),
        GA4SessionsDaily,
        property_ids,
    ).all()


def _weighted_position(rows) -> float | None:
    impressions = sum(r.impressions for r in rows)
    if impressions:
        return sum(r.position * r.impressions for r in rows) / impressions
    positions = [r.position for r in rows if r.position]
    return sum(positions) / len(positions) if positions else None


def _query_aggregates(rows) -> dict[str, dict]:
    """Aggregate query-level GSC rows by query text. Each query appears once
    regardless of how many pages or days it spans (duplicate suppression)."""
    by_query: dict[str, list] = {}
    for r in rows:
        if r.query:
            by_query.setdefault(r.query.strip().lower(), []).append(r)
    out = {}
    for q, rs in by_query.items():
        pos = _weighted_position(rs)
        clicks = sum(r.clicks for r in rs)
        impressions = sum(r.impressions for r in rs)
        out[q] = {
            "query": q,
            "clicks": clicks,
            "impressions": impressions,
            "ctr": round(clicks / impressions, 4) if impressions else None,
            "position": round(pos, 1) if pos is not None else None,
            "pages": sorted({_norm_path(r.page) for r in rs if r.page} - {None}),
        }
    return out


def _branded_terms(db: Session, property_ids) -> list[str]:
    """Deterministic branded-query terms: each in-scope property's full name,
    its slug, and any two-word prefix of the name (e.g. "douglas county").
    Single generic tokens like "housing" are deliberately not used."""
    q = db.query(Property)
    if property_ids is not None:
        q = q.filter(Property.id.in_(property_ids))
    terms = []
    for p in q.all():
        name = p.name.strip().lower()
        terms.append(name)
        if p.slug:
            terms.append(p.slug.strip().lower())
        words = name.split()
        if len(words) >= 2:
            terms.append(" ".join(words[:2]))
    return [t for t in terms if len(t) >= 4]


def _is_branded(query: str, branded_terms: list[str]) -> bool:
    return any(t in query for t in branded_terms)


def _bucket(position: float) -> str:
    for label, ceiling in RANK_BUCKETS:
        if position <= ceiling:
            return label
    return RANK_BUCKETS[-1][0]


def _source_bounds(db, model, property_ids):
    first = _scoped(db.query(func.min(model.date)), model, property_ids).scalar()
    last = _scoped(db.query(func.max(model.date)), model, property_ids).scalar()
    return first, last


def _coverage_pair(db, model, property_ids, window, prev_win):
    """Coverage of the current and previous windows for one source, plus the
    comparability verdict."""
    first, last = _source_bounds(db, model, property_ids)
    configured = first is not None
    cur = coverage_state(
        window[0], window[1], first, last, configured, FRESHNESS_THRESHOLD_DAYS
    )
    prev = coverage_state(
        prev_win[0], prev_win[1], first, last, configured, FRESHNESS_THRESHOLD_DAYS
    )
    verdict = comparable(cur, prev)
    return cur, prev, verdict, last


# --- Sections ----------------------------------------------------------------


def _summary_section(db, property_ids, window, prev_win, want_compare):
    cur_gsc = _gsc_rows(db, property_ids, *window)
    cur_ga4 = _ga4_organic_rows(db, property_ids, *window)
    gsc_cov, _, gsc_cmp, gsc_last = _coverage_pair(
        db, GSCPerformanceDaily, property_ids, window, prev_win
    )
    # GA4 coverage bounds intentionally use all GA4 rows, not just organic:
    # "no organic rows" with a healthy sync is a real zero, not missing data.
    ga4_cov, _, ga4_cmp, ga4_last = _coverage_pair(
        db, GA4SessionsDaily, property_ids, window, prev_win
    )

    compare_gsc = want_compare and gsc_cmp["comparable"]
    compare_ga4 = want_compare and ga4_cmp["comparable"]
    prev_gsc = _gsc_rows(db, property_ids, *prev_win) if compare_gsc else []
    prev_ga4 = _ga4_organic_rows(db, property_ids, *prev_win) if compare_ga4 else []

    def gsc_metrics(rows):
        clicks = sum(r.clicks for r in rows)
        impressions = sum(r.impressions for r in rows)
        pos = _weighted_position(rows)
        return {
            "clicks": clicks,
            "impressions": impressions,
            "ctr": clicks / impressions if impressions else None,
            "position": round(pos, 1) if pos is not None else None,
        }

    def ga4_metrics(rows):
        sessions = sum(r.sessions for r in rows)
        engaged = sum(r.engaged_sessions for r in rows)
        key_events = sum(r.key_events for r in rows)
        return {
            "sessions": sessions,
            "engaged": engaged,
            "key_events": key_events,
            "cr": key_events / sessions if sessions else None,
        }

    cur_g, prev_g = gsc_metrics(cur_gsc), gsc_metrics(prev_gsc)
    cur_a, prev_a = ga4_metrics(cur_ga4), ga4_metrics(prev_ga4)

    def card(key, label, source, current, previous, state, last_data,
             unit=None, higher_is_better=True, sample=None, warning=None):
        return {
            "key": key,
            "label": label,
            "source": source,
            "state": state,
            "value": current,
            "unit": unit,
            "higher_is_better": higher_is_better,
            "comparison": compare(current, previous) if previous is not None else None,
            "comparison_warning": warning,
            "last_data_date": last_data.isoformat() if last_data else None,
            "sample": sample,
        }

    gsc_state = gsc_cov["state"] if not cur_gsc else DataState.COMPLETE.value
    ga4_state = ga4_cov["state"] if not cur_ga4 else DataState.COMPLETE.value
    # Organic rows can be absent while GA4 itself is healthy; that is a real
    # zero only when GA4 data covers the window.
    if not cur_ga4 and ga4_cov["state"] in (
        DataState.COMPLETE.value,
        DataState.SOURCE_DELAYED.value,
    ):
        ga4_state = DataState.EMPTY.value

    gsc_warn = None if compare_gsc else (gsc_cmp["warning"] if want_compare else None)
    ga4_warn = None if compare_ga4 else (ga4_cmp["warning"] if want_compare else None)

    gsc_src = "Search Console"
    ga4_src = "GA4 (organic medium)"
    p = prev_g if compare_gsc else {"clicks": None, "impressions": None, "ctr": None, "position": None}
    pa = prev_a if compare_ga4 else {"sessions": None, "engaged": None, "key_events": None, "cr": None}

    cards = [
        card("organic_clicks", "Organic clicks", gsc_src, cur_g["clicks"] if cur_gsc else None,
             p["clicks"], gsc_state, gsc_last, warning=gsc_warn),
        card("organic_impressions", "Organic impressions", gsc_src,
             cur_g["impressions"] if cur_gsc else None, p["impressions"], gsc_state,
             gsc_last, warning=gsc_warn),
        card("ctr", "Click-through rate", gsc_src,
             round(cur_g["ctr"], 4) if cur_gsc and cur_g["ctr"] is not None else None,
             round(p["ctr"], 4) if p["ctr"] is not None else None,
             gsc_state, gsc_last, unit="pct",
             sample=rate(cur_g["clicks"], cur_g["impressions"]) if cur_gsc else None,
             warning=gsc_warn),
        card("avg_position", "Average position", gsc_src,
             cur_g["position"] if cur_gsc else None, p["position"], gsc_state,
             gsc_last, higher_is_better=False, warning=gsc_warn),
        card("organic_sessions", "Organic sessions", ga4_src,
             cur_a["sessions"] if cur_ga4 else None, pa["sessions"], ga4_state,
             ga4_last, warning=ga4_warn),
        card("organic_engaged_sessions", "Organic engaged sessions", ga4_src,
             cur_a["engaged"] if cur_ga4 else None, pa["engaged"], ga4_state,
             ga4_last, warning=ga4_warn),
        card("organic_key_events", "Organic key events", ga4_src,
             cur_a["key_events"] if cur_ga4 else None, pa["key_events"], ga4_state,
             ga4_last, warning=ga4_warn),
        card("organic_conversion_rate", "Organic conversion rate", ga4_src,
             round(cur_a["cr"], 4) if cur_ga4 and cur_a["cr"] is not None else None,
             round(pa["cr"], 4) if pa["cr"] is not None else None,
             ga4_state, ga4_last, unit="pct",
             sample=rate(cur_a["key_events"], cur_a["sessions"]) if cur_ga4 else None,
             warning=ga4_warn),
    ]
    return {
        "cards": cards,
        "gsc_coverage": gsc_cov,
        "ga4_coverage": ga4_cov,
    }


def _trends_section(db, property_ids, window):
    rows = _gsc_rows(db, property_ids, *window)
    if not rows:
        return {"state": DataState.EMPTY.value, "series": []}
    by_date: dict[date, list] = {}
    for r in rows:
        by_date.setdefault(r.date, []).append(r)
    series = []
    # Dates with no data are absent, not zero-filled; the chart shows gaps.
    for d in sorted(by_date):
        rs = by_date[d]
        clicks = sum(r.clicks for r in rs)
        impressions = sum(r.impressions for r in rs)
        pos = _weighted_position(rs)
        series.append({
            "date": d.isoformat(),
            "clicks": clicks,
            "impressions": impressions,
            "ctr": round(clicks / impressions, 4) if impressions else None,
            "position": round(pos, 1) if pos is not None else None,
        })
    return {"state": DataState.COMPLETE.value, "series": series}


def _distribution_section(db, property_ids, window, prev_win, want_compare):
    cur = _query_aggregates(_gsc_rows(db, property_ids, *window))
    prev = (
        _query_aggregates(_gsc_rows(db, property_ids, *prev_win))
        if want_compare
        else {}
    )
    if not cur and not prev:
        return {
            "state": DataState.INSUFFICIENT_SAMPLE.value,
            "detail": (
                "No query-level Search Console rows in range. Connect the "
                "Search Console sync or upload a query-level export."
            ),
            "buckets": [],
            "note": QUERY_DATA_NOTE,
        }

    def counts(aggs):
        c = {label: 0 for label, _ in RANK_BUCKETS}
        for a in aggs.values():
            if a["position"] is not None:
                c[_bucket(a["position"])] += 1
        return c

    cur_counts, prev_counts = counts(cur), counts(prev)
    buckets = [
        {
            "bucket": label,
            "current": cur_counts[label],
            "previous": prev_counts[label] if prev else None,
            "change": cur_counts[label] - prev_counts[label] if prev else None,
        }
        for label, _ in RANK_BUCKETS
    ]
    return {
        "state": DataState.COMPLETE.value,
        "buckets": buckets,
        "total_queries": {
            "current": len(cur),
            "previous": len(prev) if prev else None,
        },
        "note": QUERY_DATA_NOTE,
    }


def _quadrant_section(db, property_ids, window, prev_win, branded_terms):
    cur = _query_aggregates(_gsc_rows(db, property_ids, *window))
    prev = _query_aggregates(_gsc_rows(db, property_ids, *prev_win))
    if not cur:
        return {
            "state": DataState.INSUFFICIENT_SAMPLE.value,
            "detail": "No query-level Search Console rows in range.",
            "points": [],
            "note": QUERY_DATA_NOTE,
        }
    points = []
    for q, a in cur.items():
        if a["position"] is None:
            continue
        pv = prev.get(q)
        declining = bool(
            pv
            and max(a["impressions"], pv["impressions"]) >= MIN_QUERY_IMPRESSIONS
            and (
                pv["clicks"] - a["clicks"] >= MIN_CLICK_CHANGE
                or (
                    pv["position"] is not None
                    and a["position"] - pv["position"] >= DECLINE_POSITION_DROP
                )
            )
        )
        flags = {
            "high_impressions_low_ctr": (
                a["impressions"] >= HIGH_IMPRESSIONS
                and (a["ctr"] or 0) < LOW_CTR
            ),
            "striking_distance": (
                STRIKING_DISTANCE[0] <= a["position"] <= STRIKING_DISTANCE[1]
            ),
            "strong_rank_low_clicks": (
                a["position"] <= STRONG_POSITION
                and a["impressions"] >= MIN_QUERY_IMPRESSIONS
                and (a["ctr"] or 0) < STRONG_RANK_LOW_CTR
            ),
            "declining": declining,
        }
        topics = enrich_text(a["query"]).get("topics", [])
        points.append({
            **a,
            "branded": _is_branded(q, branded_terms),
            "topics": topics,
            "flags": flags,
        })
    points.sort(key=lambda x: -x["impressions"])
    dropped = max(0, len(points) - QUADRANT_LIMIT)
    points = points[:QUADRANT_LIMIT]
    highlights = {
        key: sum(1 for x in points if x["flags"][key])
        for key in (
            "high_impressions_low_ctr",
            "striking_distance",
            "strong_rank_low_clicks",
            "declining",
        )
    }
    return {
        "state": DataState.COMPLETE.value,
        "points": points,
        "highlights": highlights,
        "dropped": dropped,
        "note": QUERY_DATA_NOTE,
        "rules": {
            "high_impressions_low_ctr": f"impressions >= {HIGH_IMPRESSIONS} and CTR < {LOW_CTR:.0%}",
            "striking_distance": f"average position {STRIKING_DISTANCE[0]:.0f} to {STRIKING_DISTANCE[1]:.0f}",
            "strong_rank_low_clicks": f"position <= {STRONG_POSITION:.0f} with impressions >= {MIN_QUERY_IMPRESSIONS} and CTR < {STRONG_RANK_LOW_CTR:.0%}",
            "declining": f"clicks down {MIN_CLICK_CHANGE}+ or position worse by {DECLINE_POSITION_DROP:.0f}+ vs previous period",
            "branded": "query contains a property name, slug, or two-word name prefix",
        },
    }


def _movers_section(db, property_ids, window, prev_win, comparable_ok):
    if not comparable_ok:
        return {
            "state": DataState.INSUFFICIENT_SAMPLE.value,
            "detail": (
                "Gains and losses need a previous period with compatible "
                "Search Console coverage."
            ),
            "gains": [],
            "losses": [],
        }
    cur = _query_aggregates(_gsc_rows(db, property_ids, *window))
    prev = _query_aggregates(_gsc_rows(db, property_ids, *prev_win))
    if not cur and not prev:
        return {
            "state": DataState.INSUFFICIENT_SAMPLE.value,
            "detail": "No query-level Search Console rows in either period.",
            "gains": [],
            "losses": [],
        }
    movers = []
    for q in set(cur) | set(prev):
        c, p = cur.get(q), prev.get(q)
        c_impr = c["impressions"] if c else 0
        p_impr = p["impressions"] if p else 0
        if max(c_impr, p_impr) < MIN_QUERY_IMPRESSIONS:
            continue
        click_change = (c["clicks"] if c else 0) - (p["clicks"] if p else 0)
        impr_change = c_impr - p_impr
        pos_change = None
        if c and p and c["position"] is not None and p["position"] is not None:
            pos_change = round(c["position"] - p["position"], 1)
        significant = abs(click_change) >= MIN_CLICK_CHANGE or (
            pos_change is not None and abs(pos_change) >= MIN_POSITION_CHANGE
        )
        if not significant:
            continue
        movers.append({
            "query": q,
            "current_clicks": c["clicks"] if c else None,
            "previous_clicks": p["clicks"] if p else None,
            "click_change": click_change,
            "current_impressions": c["impressions"] if c else None,
            "previous_impressions": p["impressions"] if p else None,
            "impression_change": impr_change,
            "current_position": c["position"] if c else None,
            "previous_position": p["position"] if p else None,
            "position_change": pos_change,
        })
    # A gain is more clicks, or a better (lower) position at equal clicks.
    gains = sorted(
        [m for m in movers if m["click_change"] > 0
         or (m["click_change"] == 0 and (m["position_change"] or 0) < 0)],
        key=lambda m: (-m["click_change"], -m["impression_change"]),
    )[:MOVERS_LIMIT]
    losses = sorted(
        [m for m in movers if m["click_change"] < 0
         or (m["click_change"] == 0 and (m["position_change"] or 0) > 0)],
        key=lambda m: (m["click_change"], m["impression_change"]),
    )[:MOVERS_LIMIT]
    return {
        "state": DataState.COMPLETE.value,
        "gains": gains,
        "losses": losses,
        "thresholds": {
            "min_impressions": MIN_QUERY_IMPRESSIONS,
            "min_click_change": MIN_CLICK_CHANGE,
            "min_position_change": MIN_POSITION_CHANGE,
        },
    }


def _landing_pages_section(db, property_ids, window):
    ga4_rows = [
        r for r in _ga4_organic_rows(db, property_ids, *window) if r.landing_page
    ]
    gsc_rows = [
        r for r in _gsc_rows(db, property_ids, *window) if r.page
    ]
    if not ga4_rows and not gsc_rows:
        return {
            "state": DataState.EMPTY.value,
            "detail": (
                "No page-level rows in range. GA4 landing pages arrive via "
                "the Google sync; Search Console pages require the sync or a "
                "page-level export."
            ),
            "rows": [],
            "match_counts": None,
            "normalization": URL_NORMALIZATION_NOTE,
        }

    ga4_by_path: dict[str, dict] = {}
    for r in ga4_rows:
        path = _norm_path(r.landing_page)
        if path is None:
            continue
        g = ga4_by_path.setdefault(
            path, {"sessions": 0, "engaged_sessions": 0, "key_events": 0}
        )
        g["sessions"] += r.sessions
        g["engaged_sessions"] += r.engaged_sessions
        g["key_events"] += r.key_events

    gsc_by_path: dict[str, dict] = {}
    for r in gsc_rows:
        path = _norm_path(r.page)
        if path is None:
            continue
        g = gsc_by_path.setdefault(path, {"clicks": 0, "impressions": 0})
        g["clicks"] += r.clicks
        g["impressions"] += r.impressions

    all_paths = set(ga4_by_path) | set(gsc_by_path)
    rows = []
    for path in all_paths:
        a = ga4_by_path.get(path)
        g = gsc_by_path.get(path)
        rows.append({
            "page": path or "/",
            "canonical_page": _canonical_page(path),
            "matched": a is not None and g is not None,
            "sessions": a["sessions"] if a else None,
            "engaged_sessions": a["engaged_sessions"] if a else None,
            "key_events": a["key_events"] if a else None,
            "conversion_rate": (
                round(a["key_events"] / a["sessions"], 4)
                if a and a["sessions"]
                else None
            ),
            "clicks": g["clicks"] if g else None,
            "impressions": g["impressions"] if g else None,
        })
    rows.sort(key=lambda r: (-(r["sessions"] or 0), -(r["clicks"] or 0)))
    dropped = max(0, len(rows) - LANDING_PAGES_LIMIT)
    matched = sum(1 for r in rows if r["matched"])
    return {
        "state": DataState.COMPLETE.value,
        "rows": rows[:LANDING_PAGES_LIMIT],
        "dropped": dropped,
        "match_counts": {
            "matched": matched,
            "ga4_only": len(ga4_by_path) - matched,
            "gsc_only": len(gsc_by_path) - matched,
        },
        "normalization": URL_NORMALIZATION_NOTE,
    }


# --- Report + opportunities ---------------------------------------------------


def _anchor(db, property_ids) -> date | None:
    candidates = []
    for model in (GSCPerformanceDaily, GA4SessionsDaily):
        _, last = _source_bounds(db, model, property_ids)
        if last:
            candidates.append(last)
    return max(candidates) if candidates else None


def build_seo_report(
    db: Session,
    property_id: int | None,
    days: int,
    want_compare: bool = False,
    today: date | None = None,
    company_id: int | None = None,
    unassigned: bool = False,
) -> dict:
    today = today or date.today()
    property_ids = _resolve_scope(db, property_id, company_id, unassigned)
    anchor = _anchor(db, property_ids) or today
    window = (anchor - timedelta(days=days - 1), anchor)
    prev_win = previous_window(*window)

    _, _, gsc_verdict, _ = _coverage_pair(
        db, GSCPerformanceDaily, property_ids, window, prev_win
    )
    branded = _branded_terms(db, property_ids)

    return {
        "window": {
            "days": days,
            "start": window[0].isoformat(),
            "end": window[1].isoformat(),
            "anchored_to_latest_data": anchor != today,
        },
        "previous_window": {
            "start": prev_win[0].isoformat(),
            "end": prev_win[1].isoformat(),
        },
        "compare_requested": want_compare,
        "summary": _summary_section(db, property_ids, window, prev_win, want_compare),
        "trends": _trends_section(db, property_ids, window),
        "ranking_distribution": _distribution_section(
            db, property_ids, window, prev_win, want_compare
        ),
        "quadrant": _quadrant_section(db, property_ids, window, prev_win, branded),
        "movers": _movers_section(
            db, property_ids, window, prev_win,
            want_compare and gsc_verdict["comparable"],
        ),
        "landing_pages": _landing_pages_section(db, property_ids, window),
    }


def seo_recommendations(db: Session, property_id: int, today: date | None = None) -> list[dict]:
    """Deterministic SEO findings for the Opportunity Engine. Same thresholds
    as the report; a finding needs at least 3 affected queries so one noisy
    query never becomes a recommendation."""
    prop = db.get(Property, property_id)
    if prop is None:
        return []
    report = build_seo_report(db, property_id, days=90, want_compare=True, today=today)
    quadrant = report["quadrant"]
    if quadrant["state"] != DataState.COMPLETE.value:
        return []

    def cite(queries):
        return [
            {
                "property_id": prop.id,
                "property_name": prop.name,
                "source_ref": f"gsc: query='{q['query']}'",
                "evidence": [
                    f"{q['impressions']} impressions, {q['clicks']} clicks, "
                    f"position {q['position']}"
                ],
            }
            for q in queries[:5]
        ]

    recs = []
    flagged = {
        key: [p for p in quadrant["points"] if p["flags"][key]]
        for key in (
            "striking_distance",
            "high_impressions_low_ctr",
            "declining",
        )
    }
    if len(flagged["striking_distance"]) >= 3:
        qs = flagged["striking_distance"]
        recs.append({
            "title": "Strengthen pages for striking-distance search queries",
            "reason": (
                f"{len(qs)} imported queries rank in positions 8 to 20, close "
                "enough that content improvements can move them to page one."
            ),
            "impact": "High",
            "effort": "Medium",
            "citations": cite(qs),
        })
    if len(flagged["high_impressions_low_ctr"]) >= 3:
        qs = flagged["high_impressions_low_ctr"]
        recs.append({
            "title": "Rewrite titles and descriptions for low-CTR search queries",
            "reason": (
                f"{len(qs)} imported queries show at least {HIGH_IMPRESSIONS} "
                f"impressions with CTR under {LOW_CTR:.0%}; the pages appear "
                "in search but rarely earn the click."
            ),
            "impact": "Medium",
            "effort": "Low",
            "citations": cite(qs),
        })
    if len(flagged["declining"]) >= 3:
        qs = flagged["declining"]
        recs.append({
            "title": "Investigate declining search queries",
            "reason": (
                f"{len(qs)} imported queries lost clicks or ranking versus "
                "the previous period. Review the mapped pages for staleness "
                "or new competition."
            ),
            "impact": "Medium",
            "effort": "Medium",
            "citations": cite(qs),
        })
    return recs
