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
from app.services.reporting_executive import build_executive_report
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
