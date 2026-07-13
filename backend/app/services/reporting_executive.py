"""Executive report (Phase 16C).

A single-property synthesis layer over the other modules. It composes, never
recomputes: organic metrics come from the SEO report, AI-referral metrics from
the dashboard, GEO from AI Visibility, the content score from Content
Intelligence, and top actions from the Opportunity Engine.

The narrative is deterministic: the same stored calculations always produce the
same sentences, no LLM. Every sentence carries the evidence it was built from
and a link to the report or page where the reader can inspect it. Two hard
lines the generator holds:
- No causation. It reports what the data shows, never that one thing caused
  another.
- No fabrication. A metric without sufficient data yields a named state, and
  the narrative simply omits any sentence it cannot support.

Metrics that belong to reports not yet built (AEO Readiness, semantic topic
coverage, cross-source gaps) appear as cards in an honest "arrives with a
later phase" state rather than as zeros.
"""

from datetime import date

from sqlalchemy.orm import Session

from app.constants import AI_TRAFFIC_DISCLOSURE
from app.models import GA4SessionsDaily, Property
from app.services.opportunity_engine import build_opportunities
from app.services.reporting import DataState, compare
from app.services.reporting_seo import build_seo_report

# Cards whose data source is a report scheduled for a later phase. Listed so
# the executive layout matches the spec without inventing numbers.
_PLANNED_CARDS = [
    ("aeo_readiness_score", "AEO Readiness score", "AEO Readiness report", "16E"),
    ("strong_semantic_topics", "Strong semantic topics", "Semantic Intelligence report", "later phase"),
    ("cross_source_gaps", "Cross-source gaps", "Semantic Intelligence report", "later phase"),
]


def _card(key, label, source, state, value=None, unit=None, comparison=None,
          higher_is_better=True, detail=None, sample=None, last_data_date=None):
    return {
        "key": key,
        "label": label,
        "source": source,
        "state": state,
        "value": value,
        "unit": unit,
        "comparison": comparison,
        "higher_is_better": higher_is_better,
        "detail": detail,
        "sample": sample,
        "last_data_date": last_data_date,
    }


def _seo_cards(seo: dict, keys: list[str]) -> dict[str, dict]:
    """Pull specific SEO summary cards by key, preserving their state,
    comparison, source, and freshness exactly as the SEO report computed them."""
    by_key = {c["key"]: c for c in seo["summary"]["cards"]}
    out = {}
    for k in keys:
        c = by_key.get(k)
        if c is None:
            continue
        out[k] = _card(
            c["key"], c["label"], c["source"], c["state"],
            value=c["value"], unit=c["unit"], comparison=c["comparison"],
            higher_is_better=c["higher_is_better"], sample=c["sample"],
            last_data_date=c["last_data_date"],
        )
    return out


def _ga4_window(db: Session, property_id: int, start: date, end: date) -> dict | None:
    """AI-referral totals for one window, direct from GA4 rows. Returns None
    when there are no GA4 rows at all (a real "not configured", not a zero)."""
    rows = (
        db.query(GA4SessionsDaily)
        .filter(
            GA4SessionsDaily.property_id == property_id,
            GA4SessionsDaily.date >= start,
            GA4SessionsDaily.date <= end,
        )
        .all()
    )
    if not rows:
        return None
    sessions = sum(r.sessions for r in rows)
    ai_sessions = sum(r.sessions for r in rows if r.is_ai_referral)
    return {
        "sessions": sessions,
        "ai_sessions": ai_sessions,
        "ai_share": ai_sessions / sessions if sessions else 0.0,
        "last": max(r.date for r in rows).isoformat(),
    }


def _ai_referral_cards(
    db: Session, property_id: int, window, prev_win, want_compare: bool
) -> list[dict]:
    cur = _ga4_window(db, property_id, window[0], window[1])
    if cur is None:
        state = DataState.NOT_CONFIGURED.value
        return [
            _card("ai_referral_sessions", "AI referral sessions", "GA4", state,
                  detail="No GA4 data in range."),
            _card("ai_share", "AI share of sessions", "GA4", state, unit="pct",
                  detail="No GA4 data in range."),
        ]
    prev = _ga4_window(db, property_id, prev_win[0], prev_win[1]) if want_compare else None
    ai_cmp = compare(cur["ai_sessions"], prev["ai_sessions"] if prev else None)
    share_cmp = compare(
        round(cur["ai_share"], 4), round(prev["ai_share"], 4) if prev else None
    )
    return [
        _card("ai_referral_sessions", "AI referral sessions", "GA4",
              DataState.COMPLETE.value, value=cur["ai_sessions"],
              comparison=ai_cmp if want_compare else None, last_data_date=cur["last"],
              detail=AI_TRAFFIC_DISCLOSURE),
        _card("ai_share", "AI share of sessions", "GA4",
              DataState.COMPLETE.value, value=round(cur["ai_share"], 4),
              unit="pct", comparison=share_cmp if want_compare else None,
              last_data_date=cur["last"],
              sample={"numerator": cur["ai_sessions"], "denominator": cur["sessions"]},
              detail=AI_TRAFFIC_DISCLOSURE),
    ]


def _geo_card(av: dict) -> dict:
    """AI mention rate, sample-gated exactly as AI Visibility gates it."""
    if not av.get("has_queries"):
        return _card("ai_mention_rate", "AI mention rate", "AI Visibility",
                     DataState.NOT_CONFIGURED.value, unit="pct",
                     detail="No AI Visibility queries have been run.")
    sample = av["sample"]
    mention = av["mention"]
    if not sample["sufficient"]:
        return _card(
            "ai_mention_rate", "AI mention rate", "AI Visibility",
            DataState.INSUFFICIENT_SAMPLE.value, unit="pct",
            sample={"numerator": mention["mentions"], "denominator": sample["total_queries"]},
            detail=(
                f"{sample['total_queries']} of {sample['minimum']} minimum "
                "queries run; rate not calculated."
            ),
        )
    return _card(
        "ai_mention_rate", "AI mention rate", "AI Visibility",
        DataState.COMPLETE.value, value=round(mention["rate"], 4), unit="pct",
        sample={"numerator": mention["mentions"], "denominator": mention["queries"]},
        detail=f"Brand mentioned in {mention['mentions']} of {mention['queries']} tested responses.",
    )


def _content_card(ci: dict) -> dict:
    if not ci.get("has_content") or not ci.get("score"):
        return _card("content_score", "Content Intelligence score", "Content IQ",
                     DataState.AWAITING_DATA.value,
                     detail="No website content ingested for this property.")
    score = ci["score"]
    return _card("content_score", "Content Intelligence score", "Content IQ",
                 DataState.COMPLETE.value, value=score["value"],
                 detail=f"Grade {score['grade']}.")


def _opportunities_card(opps: dict) -> dict:
    n = len(opps["opportunities"])
    return _card("actionable_opportunities", "Actionable opportunities",
                 "Opportunity Engine", DataState.COMPLETE.value, value=n,
                 detail=opps["summary"])


def _planned_cards() -> list[dict]:
    return [
        _card(key, label, source, DataState.NOT_CONFIGURED.value,
              detail=f"Arrives with the {source} ({phase}).")
        for key, label, source, phase in _PLANNED_CARDS
    ]


# --- Deterministic narrative --------------------------------------------------


def _narrative(cards: dict[str, dict], seo: dict, opps: dict, want_compare: bool) -> list[dict]:
    """Build cited sentences from the composed calculations. Each item is
    {text, evidence:[str], link:{label,href}}. Sentences are emitted only when
    their supporting data exists. No causal language."""
    items: list[dict] = []

    def link(label, href):
        return {"label": label, "href": href}

    # Largest organic movement (up or down), only when comparisons ran and the
    # movement is nonzero (a flat metric is not a "movement" worth narrating).
    if want_compare:
        moved = [
            c for c in cards.values()
            if c.get("comparison") and c["comparison"]["change"] is not None
            and c["comparison"]["pct_change"] is not None
            and c["comparison"]["direction"] != "flat"
        ]
        if moved:
            def magnitude(c):
                return abs(c["comparison"]["pct_change"])
            biggest = max(moved, key=magnitude)
            cmp = biggest["comparison"]
            direction = "increased" if cmp["change"] > 0 else "decreased"
            pct = abs(cmp["pct_change"]) * 100
            items.append({
                "text": (
                    f"{biggest['label']} {direction} {pct:.1f} percent versus the "
                    f"previous period, from {cmp['previous']} to {cmp['current']}."
                ),
                "evidence": [f"{biggest['source']}: {cmp['previous']} to {cmp['current']}"],
                "link": link("SEO Performance", "/reports/seo"),
            })

    # Strongest SEO signal: the largest striking-distance or low-CTR group.
    quad = seo.get("quadrant", {})
    if quad.get("state") == DataState.COMPLETE.value:
        hi = quad.get("highlights", {})
        if hi.get("striking_distance"):
            items.append({
                "text": (
                    f"{hi['striking_distance']} imported search queries rank in "
                    "positions 8 to 20, within reach of page one."
                ),
                "evidence": [f"Search Console: {hi['striking_distance']} queries in positions 8-20"],
                "link": link("SEO Performance", "/reports/seo"),
            })
        elif hi.get("high_impressions_low_ctr"):
            items.append({
                "text": (
                    f"{hi['high_impressions_low_ctr']} imported search queries draw "
                    "impressions but few clicks."
                ),
                "evidence": [f"Search Console: {hi['high_impressions_low_ctr']} high-impression low-CTR queries"],
                "link": link("SEO Performance", "/reports/seo"),
            })

    # Strongest GEO signal, sample-gated. State the sample either way.
    geo = cards.get("ai_mention_rate")
    if geo:
        if geo["state"] == DataState.COMPLETE.value:
            items.append({
                "text": (
                    f"AI Visibility testing mentioned the property in "
                    f"{geo['sample']['numerator']} of {geo['sample']['denominator']} "
                    "tested responses."
                ),
                "evidence": [geo["detail"]],
                "link": link("AI Visibility", "/ai-visibility"),
            })
        elif geo["state"] == DataState.INSUFFICIENT_SAMPLE.value:
            items.append({
                "text": (
                    "AI Visibility testing has not run enough queries to report a "
                    f"mention rate yet ({geo['sample']['denominator']} run)."
                ),
                "evidence": [geo["detail"]],
                "link": link("AI Visibility", "/ai-visibility"),
            })

    # Highest-priority opportunity, verbatim from the engine (already cited).
    if opps["opportunities"]:
        top = opps["opportunities"][0]
        items.append({
            "text": (
                f"The highest-priority recommendation is to {top['title'][0].lower()}"
                f"{top['title'][1:]}."
            ),
            "evidence": [top["reason"]] if top.get("reason") else [],
            "link": link("Opportunities", "/opportunities"),
        })

    if not items:
        items.append({
            "text": (
                "There is not yet enough connected data to summarize performance "
                "for this property. Connect Search Console and GA4, and run AI "
                "Visibility queries, to build the executive summary."
            ),
            "evidence": [],
            "link": link("Uploads", "/uploads"),
        })
    return items


# --- Top actions --------------------------------------------------------------


def _top_actions(opps: dict, limit: int = 3) -> list[dict]:
    actions = []
    for o in opps["opportunities"][:limit]:
        actions.append({
            "title": o["title"],
            "source_modules": [o["source_label"]] + o.get("corroborating_sources", []),
            "impact": o.get("impact"),
            "effort": o.get("effort"),
            "supporting_signal_count": 1 + len(o.get("corroborating_sources", [])),
            "explanation": o.get("reason"),
            "citations": o.get("citations", []),
            "state": o.get("state"),
            "priority": o.get("priority"),
        })
    return actions


def build_executive_report(
    db: Session,
    property_id: int | None,
    days: int,
    want_compare: bool = False,
    today: date | None = None,
    window: tuple[date, date] | None = None,
    prev_window: tuple[date, date] | None = None,
) -> dict:
    """Executive report is per-property. Portfolio/company scope returns a
    scope_required state rather than blending incomparable properties.

    window/prev_window override the data-anchored window so a caller (the
    Monthly Briefing) can request a specific calendar month; every metric in
    the report then shares that one period definition."""
    today = today or date.today()
    if property_id is None:
        return {
            "scope_required": True,
            "message": "Select a single property to view its executive report.",
        }
    prop = db.get(Property, property_id)
    if prop is None:
        raise ValueError("Property not found.")

    seo = build_seo_report(
        db, property_id, days, want_compare=want_compare, today=today,
        window=window, prev_window=prev_window,
    )
    # Anchor the AI-referral comparison to the SEO report's exact windows so
    # every metric on the executive report shares one period definition.
    window = (
        date.fromisoformat(seo["window"]["start"]),
        date.fromisoformat(seo["window"]["end"]),
    )
    prev_win = (
        date.fromisoformat(seo["previous_window"]["start"]),
        date.fromisoformat(seo["previous_window"]["end"]),
    )

    from app.services.ai_visibility import analyze_ai_visibility
    from app.services.content_intelligence import analyze_property
    from app.services.reporting_audience import top_cities_for_window

    try:
        av = analyze_ai_visibility(db, property_id, today=today)
    except Exception:
        av = {"has_queries": False}
    try:
        ci = analyze_property(db, property_id, today=today)
    except Exception:
        ci = {"has_content": False}
    opps = build_opportunities(db, property_id, today=today)

    cards: dict[str, dict] = {}
    cards.update(_seo_cards(seo, [
        "organic_clicks", "organic_impressions",
        "organic_sessions", "organic_key_events",
    ]))
    for c in _ai_referral_cards(db, property_id, window, prev_win, want_compare):
        cards[c["key"]] = c
    geo = _geo_card(av)
    cards[geo["key"]] = geo
    content = _content_card(ci)
    cards[content["key"]] = content
    opp_card = _opportunities_card(opps)
    cards[opp_card["key"]] = opp_card

    ordered = [
        "organic_clicks", "organic_impressions", "organic_sessions",
        "organic_key_events", "ai_referral_sessions", "ai_share",
        "ai_mention_rate", "content_score", "actionable_opportunities",
    ]
    card_list = [cards[k] for k in ordered if k in cards] + _planned_cards()

    return {
        "scope_required": False,
        "property_id": property_id,
        "property_name": prop.name,
        "window": seo["window"],
        "previous_window": seo["previous_window"],
        "compare_requested": want_compare,
        "cards": card_list,
        "narrative": _narrative(cards, seo, opps, want_compare),
        "top_actions": _top_actions(opps),
        "top_cities": top_cities_for_window(db, property_id, window[0], window[1]),
        "generated_on": today.isoformat(),
    }
