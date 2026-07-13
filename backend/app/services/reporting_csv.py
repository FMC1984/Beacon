"""CSV export for report sections (Phase 16C).

Exports the underlying data of a report section as a flat CSV, with each row
carrying its own metric definition, source, freshness, sample, and data-status
note so the file is self-describing. Client-safe by construction: it reads only
the composed report payloads, which never contain chunk ids, vector values,
retrieval latency, or other internal metadata.

Missing values are written as the state name (for example "not_configured"),
never as 0, matching what the on-screen report shows.
"""

import csv
import io
from datetime import date

from sqlalchemy.orm import Session

from app.constants import APP_VERSION
from app.models import Property
from app.services.reporting_aeo import build_aeo_report
from app.services.reporting_audience import build_audience_report
from app.services.reporting_content_impact import build_content_impact_report
from app.services.reporting_executive import build_executive_report
from app.services.reporting_geo import build_geo_report
from app.services.reporting_seo import build_seo_report

# Human definitions for every exported metric key. Kept here so the CSV can
# stand alone away from the app.
_DEFINITIONS = {
    "organic_clicks": "Search Console clicks from organic search in the window.",
    "organic_impressions": "Search Console impressions from organic search in the window.",
    "ctr": "Organic clicks divided by organic impressions.",
    "avg_position": "Impression-weighted average Search Console position (lower is better).",
    "organic_sessions": "GA4 sessions with session medium 'organic'.",
    "organic_engaged_sessions": "GA4 engaged sessions from organic medium.",
    "organic_key_events": "GA4 key events from organic-medium sessions.",
    "organic_conversion_rate": "Organic key events divided by organic sessions.",
    "ai_referral_sessions": "GA4 sessions classified as AI referrals.",
    "ai_share": "AI referral sessions divided by all sessions.",
    "ai_mention_rate": "Share of tested AI responses that mentioned the property (sample-gated).",
    "content_score": "Content Intelligence score for ingested website content.",
    "actionable_opportunities": "Count of actionable recommendations from the Opportunity Engine.",
    "aeo_readiness_score": "AEO Readiness score (arrives with the AEO Readiness report).",
    "strong_semantic_topics": "Count of strongly covered topics (arrives with Semantic Intelligence).",
    "cross_source_gaps": "Count of cross-source content gaps (arrives with Semantic Intelligence).",
}

_STATE_NOTES = {
    "complete": "",
    "partial_period": "Window only partially covered by this source.",
    "awaiting_data": "Source configured, no data yet.",
    "source_delayed": "Latest data older than expected for this source.",
    "not_configured": "Source not configured for this property.",
    "insufficient_sample": "Sample below the minimum; no rate calculated.",
    "failed_source": "Source failed to return data.",
    "empty": "No data in the selected range.",
}

_HEADER = [
    "metric", "definition", "value", "unit", "source",
    "last_updated", "sample_numerator", "sample_denominator",
    "data_status", "data_status_note",
]


def _value_cell(card: dict) -> str:
    """The value if complete, otherwise the state name. Never a substituted 0."""
    if card["state"] != "complete" or card.get("value") is None:
        return card["state"]
    v = card["value"]
    if card.get("unit") == "pct":
        return f"{round(v * 100, 2)}%"
    return str(v)


def _card_row(card: dict) -> list[str]:
    sample = card.get("sample") or {}
    return [
        card["label"],
        _DEFINITIONS.get(card["key"], ""),
        _value_cell(card),
        card.get("unit") or "",
        card.get("source") or "",
        card.get("last_data_date") or "",
        str(sample.get("numerator", "")) if sample else "",
        str(sample.get("denominator", "")) if sample else "",
        card["state"],
        _STATE_NOTES.get(card["state"], ""),
    ]


def _preamble(writer, title, prop_name, window, today):
    writer.writerow([f"Beacon {title}"])
    writer.writerow(["Beacon version", APP_VERSION])
    writer.writerow(["Property", prop_name])
    if window:
        writer.writerow(["Window", f"{window['start']} to {window['end']}"])
    writer.writerow(["Generated", today.isoformat()])
    writer.writerow([
        "Note",
        "Missing values are shown as their data state, never as zero.",
    ])
    writer.writerow([])


def build_seo_csv(
    db: Session, property_id: int | None, days: int, want_compare: bool,
    today: date | None = None, company_id: int | None = None, unassigned: bool = False,
) -> tuple[str, str]:
    today = today or date.today()
    report = build_seo_report(
        db, property_id, days, want_compare=want_compare, today=today,
        company_id=company_id, unassigned=unassigned,
    )
    prop_name = "Portfolio"
    if property_id is not None:
        prop = db.get(Property, property_id)
        prop_name = prop.name if prop else "Unknown"

    buf = io.StringIO()
    w = csv.writer(buf)
    _preamble(w, "SEO Performance export", prop_name, report["window"], today)
    w.writerow(_HEADER)
    for card in report["summary"]["cards"]:
        w.writerow(_card_row(card))

    # Ranking distribution as its own labeled block.
    dist = report["ranking_distribution"]
    if dist["state"] == "complete":
        w.writerow([])
        w.writerow(["Ranking distribution (imported Search Console queries)"])
        w.writerow(["position_bucket", "current_queries", "previous_queries", "change"])
        for b in dist["buckets"]:
            w.writerow([
                b["bucket"], b["current"],
                "" if b["previous"] is None else b["previous"],
                "" if b["change"] is None else b["change"],
            ])
    return buf.getvalue(), "beacon-seo-performance.csv"


def build_executive_csv(
    db: Session, property_id: int | None, days: int, want_compare: bool,
    today: date | None = None,
) -> tuple[str, str]:
    today = today or date.today()
    report = build_executive_report(
        db, property_id, days, want_compare=want_compare, today=today
    )
    if report.get("scope_required"):
        raise ValueError(report["message"])

    buf = io.StringIO()
    w = csv.writer(buf)
    _preamble(w, "Executive report export", report["property_name"], report["window"], today)
    w.writerow(_HEADER)
    for card in report["cards"]:
        w.writerow(_card_row(card))

    w.writerow([])
    w.writerow(["Top actions"])
    w.writerow(["priority", "action", "impact", "effort", "supporting_signals", "source_modules", "explanation"])
    for a in report["top_actions"]:
        w.writerow([
            a.get("priority", ""), a["title"], a.get("impact") or "",
            a.get("effort") or "", a.get("supporting_signal_count", ""),
            "; ".join(a.get("source_modules", [])), a.get("explanation") or "",
        ])
    return buf.getvalue(), "beacon-executive-report.csv"


def _rate_cell(r: dict) -> str:
    """A sampled rate as 'value (num/denom)', or the state when withheld."""
    if r["value"] is None:
        return f"{r['state']} ({r['numerator']}/{r['denominator']})"
    return f"{round(r['value'] * 100, 1)}% ({r['numerator']}/{r['denominator']})"


def build_geo_csv(
    db: Session, property_id: int | None, today: date | None = None,
) -> tuple[str, str]:
    today = today or date.today()
    report = build_geo_report(db, property_id, today=today)
    if report.get("scope_required"):
        raise ValueError(report["message"])

    prop_name = report["property_name"]
    buf = io.StringIO()
    w = csv.writer(buf)
    _preamble(w, "GEO Visibility export", prop_name, None, today)

    if not report.get("has_queries"):
        w.writerow(["No AI Visibility queries have been run for this property."])
        return buf.getvalue(), "beacon-geo-visibility.csv"

    s = report["summary"]
    w.writerow(["Summary metric", "value", "note"])
    w.writerow(["Queries completed", s["queries_completed"], ""])
    w.writerow(["Platforms tested", len(s["platforms_tested"]),
                "; ".join(p["label"] for p in s["platforms_tested"])])
    w.writerow(["Mention count", s["mention_count"], ""])
    w.writerow(["Responses with a citation", s["citation_count"], ""])
    w.writerow(["Mention rate", _rate_cell(s["mention_rate"]), "numerator/denominator shown"])
    w.writerow(["Citation rate", _rate_cell(s["citation_rate"]), "numerator/denominator shown"])
    w.writerow(["Owned-domain citations", s["owned_domain_citations"], ""])
    w.writerow(["Competitor appearances", s["competitor_appearances"], ""])
    w.writerow(["Last run", s["last_run"] or "", ""])

    w.writerow([])
    w.writerow(["Source landscape"])
    w.writerow(["domain", "category", "cited_in_responses", "pct_of_completed", "platforms"])
    for d in report["source_landscape"]["domains"]:
        w.writerow([
            d["domain"], d["category_label"], d["cited_in_responses"],
            "" if d["pct_of_completed"] is None else f"{round(d['pct_of_completed'] * 100, 1)}%",
            "; ".join(d["platforms"]),
        ])

    cs = report["competitor_share"]
    w.writerow([])
    w.writerow([cs["label"]])  # "Share of tested AI answers", never market share
    if cs["has_competitors"] and cs["share_of_voice"]:
        w.writerow(["entity", "is_property", "mentions", "share"])
        for e in cs["share_of_voice"].get("entities", []):
            w.writerow([
                e["name"], "yes" if e["is_property"] else "no", e["mentions"],
                "" if e.get("share") is None else f"{round(e['share'] * 100, 1)}%",
            ])
    else:
        w.writerow(["No competitors configured, or sample below minimum."])
    return buf.getvalue(), "beacon-geo-visibility.csv"


def build_aeo_csv(
    db: Session, property_id: int | None, today: date | None = None,
) -> tuple[str, str]:
    today = today or date.today()
    report = build_aeo_report(db, property_id, today=today)
    if report.get("scope_required"):
        raise ValueError(report["message"])

    buf = io.StringIO()
    w = csv.writer(buf)
    _preamble(w, "AEO Readiness export", report["property_name"], None, today)

    if not report.get("has_content"):
        w.writerow(["No website content ingested for this property."])
        return buf.getvalue(), "beacon-aeo-readiness.csv"

    score = report["score"]
    w.writerow(["AEO Readiness score", score["value"], f"grade {score['grade']}"])
    w.writerow([])
    w.writerow(["Score components"])
    w.writerow(["component", "weight", "raw_value", "excluded", "rule", "explanation"])
    for c in score["components"]:
        w.writerow([
            c["label"], c["weight"],
            "excluded" if c["excluded"] else c["raw_value"],
            "yes" if c["excluded"] else "no",
            c["rule"], c["explanation"],
        ])

    w.writerow([])
    w.writerow(["Question coverage heatmap (state per page)"])
    hm = report["heatmap"]
    w.writerow(["question", "importance"] + hm["pages"])
    for row in hm["rows"]:
        by_page = {c["page"]: c for c in row["cells"]}
        w.writerow(
            [row["question"], row["importance"]]
            + [by_page[p]["state"] + (" (stale)" if by_page[p]["stale"] else "") for p in hm["pages"]]
        )

    w.writerow([])
    w.writerow(["Citation readiness", report["citation_readiness"]["value"]])
    w.writerow([report["citation_readiness"]["disclaimer"]])
    return buf.getvalue(), "beacon-aeo-readiness.csv"


def build_content_impact_csv(
    db: Session, property_id: int | None, window: int = 30, today: date | None = None,
) -> tuple[str, str]:
    today = today or date.today()
    report = build_content_impact_report(db, property_id, window=window, today=today)
    if report.get("scope_required"):
        raise ValueError(report["message"])

    buf = io.StringIO()
    w = csv.writer(buf)
    _preamble(w, "Content Impact export", report["property_name"], None, today)
    w.writerow(["Caveat", report["caveat"]])
    w.writerow(["Comparison window (days before/after)", report["window"]])
    w.writerow([])

    if not report["has_changes"]:
        w.writerow(["No content changes recorded for this property."])
        return buf.getvalue(), "beacon-content-impact.csv"

    w.writerow([
        "change", "type", "date", "metric", "before", "after",
        "observed_change", "after_window_complete", "state",
    ])
    for c in report["changes"]:
        cmp = c["comparison"]
        for m in cmp["metrics"]:
            change = m["comparison"]["change"] if m["comparison"] else ""
            w.writerow([
                c["change_title"], c["change_type"], c["date_implemented"],
                m["label"],
                "" if m["before"] is None else m["before"],
                "" if m["after"] is None else m["after"],
                "" if change == "" or change is None else change,
                "yes" if cmp["after_complete"] else "no",
                m["state"],
            ])
    return buf.getvalue(), "beacon-content-impact.csv"


def _pct_cell(share: float | None) -> str:
    """A 0-1 share as a percentage, or empty when not applicable (never 0%)."""
    return "" if share is None else f"{round(share * 100, 1)}%"


def build_audience_csv(
    db: Session,
    property_id: int | None = None,
    days: int = 30,
    company_id: int | None = None,
    unassigned: bool = False,
    today: date | None = None,
) -> tuple[str, str]:
    today = today or date.today()
    report = build_audience_report(
        db, property_id, days, company_id=company_id, unassigned=unassigned,
        today=today, city_limit=100000,  # export carries the full city list
    )

    buf = io.StringIO()
    w = csv.writer(buf)
    _preamble(w, "Audience geography export", report["scope_label"], None, today)

    if not report.get("has_data"):
        w.writerow([report["message"]])
        return buf.getvalue(), "beacon-audience.csv"

    win = report["window"]
    s = report["summary"]
    w.writerow(["Window", f"{win['start']} to {win['end']}"])
    w.writerow(["Note", report["geography_note"]])
    w.writerow(["AI traffic disclosure", report["disclosure"]])
    if not report["geography_available"]:
        w.writerow(["Geography", report["geography_message"]])
    w.writerow([])

    w.writerow(["Summary metric", "value", "note"])
    w.writerow(["Total sessions", s["total_sessions"], ""])
    w.writerow(["Located share", _pct_cell(s["located_share"]),
                f"{s['located_sessions']} of {s['total_sessions']} sessions have a city"])
    w.writerow(["Cities represented", s["distinct_cities"], ""])
    w.writerow(["Regions represented", s["distinct_regions"], ""])
    w.writerow(["AI referral sessions", s["ai_sessions"], report["disclosure"]])
    w.writerow(["AI share of sessions", _pct_cell(s["ai_share"]), ""])
    w.writerow([])

    w.writerow([
        "City", "Region", "sessions", "share_of_sessions", "users",
        "engaged_sessions", "engagement_rate", "key_events",
        "ai_sessions", "ai_share",
    ])
    for c in report["cities"]:
        w.writerow([
            c["city"], c["region"] or "", c["sessions"],
            _pct_cell(c["sessions_share"]), c["users"], c["engaged_sessions"],
            _pct_cell(c["engagement_rate"]), c["key_events"],
            c["ai_sessions"], _pct_cell(c["ai_share"]),
        ])

    w.writerow([])
    w.writerow(["Region", "sessions", "share_of_sessions", "users"])
    for rg in report["regions"]:
        w.writerow([
            rg["region"], rg["sessions"], _pct_cell(rg["sessions_share"]),
            rg["users"],
        ])

    return buf.getvalue(), "beacon-audience.csv"
