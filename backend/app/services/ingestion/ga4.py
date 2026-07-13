"""GA4 traffic export parser + ingester.

Tolerant by design: Beacon adapts to the many shapes a GA4 CSV can take rather
than rejecting on formatting. It handles preamble comment lines, a segment
header row above the real header, duplicate metric columns (one per segment),
extra dimensions it does not need (Event name, Search term), combined
"Session source / medium", "Landing page + query string", a trailing Grand
total row, and "Date + hour (YYYYMMDDHH)" (the calendar date is taken from the
leading 8 digits).

The one thing it will NOT do is silently produce wrong numbers. A GA4 export
broken down by Event name repeats each session across many event rows, so naive
summing overcounts sessions several-fold. When Beacon detects that shape it
collapses to TRUE sessions using the once-per-session `session_start` event
(this reproduces GA4's own Grand Total exactly) and reports that it did so.

Re-uploads are idempotent by replacement: for the property and the set of dates
present in the file, existing GA4 rows are deleted before insert.
"""

from dataclasses import dataclass, field
from datetime import date

from sqlalchemy.orm import Session

from app.models import GA4SessionsDaily, Upload
from app.services.classifier import get_classifier
from app.services.ingestion.common import (
    UploadValidationError,
    parse_export_date,
    parse_int,
    read_csv_matrix,
)

COLUMN_ALIASES = {
    "date": "date",
    "date + hour (yyyymmddhh)": "date",
    "date + hour": "date",
    "nth day": "nth_day",  # recognized only so we can reject it with a clear message
    "session source / medium": "source_medium",
    "session source/medium": "source_medium",
    "source / medium": "source_medium",
    "source/medium": "source_medium",
    "session source": "source",
    "session medium": "medium",
    "session campaign": "campaign",
    "session campaign name": "campaign",
    "landing page": "landing_page",
    "landing page + query string": "landing_page",
    "city": "city",
    "town/city": "city",
    "region": "region",
    "event name": "event_name",
    "sessions": "sessions",
    "engaged sessions": "engaged_sessions",
    "total users": "total_users",
    "users": "total_users",
    "key events": "key_events",
    "conversions": "key_events",
}

TOTALS_MARKERS = ("grand total", "total", "totals")
SESSION_MARKER_EVENT = "session_start"


@dataclass
class ParseResult:
    rows: list[dict] = field(default_factory=list)
    skipped: list[dict] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def _get(row: list[str], idx: int | None) -> str:
    if idx is None or idx >= len(row):
        return ""
    return (row[idx] or "").strip()


def _split_source_medium(combined: str) -> tuple[str, str]:
    source, _, medium = combined.partition("/")
    return source.strip(), (medium.strip() or "(none)")


# GA4 marks an unresolved dimension with these literals. Treat them as "no
# location" (NULL) rather than storing the placeholder as if it were a place.
_GEO_UNSET = {"(not set)", "(not provided)", "(other)"}


def _geo(raw: str) -> str | None:
    value = (raw or "").strip()
    if not value or value.lower() in _GEO_UNSET:
        return None
    return value


def parse_ga4_csv(data: bytes) -> ParseResult:
    col_index, data_rows, header_line = read_csv_matrix(data, COLUMN_ALIASES)

    def first(key: str) -> int | None:
        cols = col_index.get(key)
        return cols[0] if cols else None

    missing = []
    if "date" not in col_index:
        if "nth_day" in col_index:
            raise UploadValidationError(
                "This GA4 export uses a relative 'Nth day' dimension, which has no "
                "real calendar dates. Re-export the report with the 'Date' (or "
                "'Date + hour') dimension so Beacon can place the data in time."
            )
        missing.append("Date")
    if "sessions" not in col_index:
        missing.append("Sessions")
    if "source" not in col_index and "source_medium" not in col_index:
        missing.append("Session source (or Session source / medium)")
    if missing:
        raise UploadValidationError(
            "GA4 export is missing required columns: " + ", ".join(missing) + ". "
            "Export the report with Date and Session source dimensions included. "
            "Found columns: " + ", ".join(sorted(col_index)) + "."
        )

    date_i = first("date")
    source_i = first("source")
    source_medium_i = first("source_medium")
    medium_i = first("medium")
    campaign_i = first("campaign")
    landing_i = first("landing_page")
    city_i = first("city")
    region_i = first("region")
    event_i = first("event_name")
    sessions_i = first("sessions")
    engaged_i = first("engaged_sessions")
    users_i = first("total_users")
    key_events_i = first("key_events")

    # Pass 1: parse every usable data row into a normalized record.
    records: list[dict] = []
    result = ParseResult()
    for offset, row in enumerate(data_rows):
        line_no = header_line + 1 + offset
        if not any((c or "").strip() for c in row):
            continue
        date_raw = _get(row, date_i)
        # A Grand total row has empty dimensions; skip it quietly.
        if not date_raw and not _get(row, source_i) and not _get(row, source_medium_i):
            continue
        if date_raw.lower() in TOTALS_MARKERS:
            result.skipped.append({"line": line_no, "reason": "totals row"})
            continue
        parsed_date = parse_export_date(date_raw)
        if parsed_date is None:
            result.skipped.append(
                {"line": line_no, "reason": f"unparseable date '{date_raw}'"}
            )
            continue
        if source_i is not None:
            source = _get(row, source_i)
            medium = _get(row, medium_i) or "(none)"
        else:
            source, medium = _split_source_medium(_get(row, source_medium_i))
        if not source:
            result.skipped.append({"line": line_no, "reason": "empty source"})
            continue
        records.append(
            {
                "date": parsed_date,
                "source_line": line_no,
                "session_source": source,
                "session_medium": medium,
                "session_campaign": _get(row, campaign_i) or None,
                "landing_page": _get(row, landing_i) or None,
                "city": _geo(_get(row, city_i)),
                "region": _geo(_get(row, region_i)),
                "event_name": _get(row, event_i).lower() if event_i is not None else None,
                "sessions": parse_int(_get(row, sessions_i)),
                "engaged_sessions": parse_int(_get(row, engaged_i)),
                "total_users": parse_int(_get(row, users_i)),
                "key_events": parse_int(_get(row, key_events_i)),
            }
        )

    if event_i is not None:
        result.rows = _collapse_event_level(records)
        result.warnings.append(
            "This GA4 export is broken down by event, so each visit appears on "
            "several rows. Beacon counted true sessions from the once-per-session "
            "'session_start' event (which matches GA4's own totals) instead of "
            "summing every row, which would multiply the session count."
        )
    else:
        result.rows = [
            {k: v for k, v in rec.items() if k != "event_name"} for rec in records
        ]

    if not result.rows:
        raise UploadValidationError("No ingestable data rows found in the file.")
    return result


def _collapse_event_level(records: list[dict]) -> list[dict]:
    """Event-grained export -> one honest row per (source, medium, date, landing).
    Sessions/engaged/users come only from session_start rows (once per session);
    key events sum across all event rows (a conversion fires on its own event)."""
    groups: dict[tuple, dict] = {}
    saw_session_marker = False
    for rec in records:
        key = (
            rec["session_source"],
            rec["session_medium"],
            rec["date"],
            rec["landing_page"],
            rec["city"],
            rec["region"],
        )
        g = groups.get(key)
        if g is None:
            g = {
                "date": rec["date"],
                "source_line": rec["source_line"],
                "session_source": rec["session_source"],
                "session_medium": rec["session_medium"],
                "session_campaign": rec["session_campaign"],
                "landing_page": rec["landing_page"],
                "city": rec["city"],
                "region": rec["region"],
                "sessions": 0,
                "engaged_sessions": 0,
                "total_users": 0,
                "key_events": 0,
            }
            groups[key] = g
        g["key_events"] += rec["key_events"]
        if rec["event_name"] == SESSION_MARKER_EVENT:
            saw_session_marker = True
            g["sessions"] += rec["sessions"]
            g["engaged_sessions"] += rec["engaged_sessions"]
            g["total_users"] += rec["total_users"]

    if not saw_session_marker:
        raise UploadValidationError(
            "This GA4 export is broken down by event but has no 'session_start' "
            "rows, so Beacon cannot recover an honest session count from it "
            "(summing would count each visit many times). Re-export the report "
            "without the 'Event name' dimension, or include session_start events."
        )
    # Keep only groups that carry a real metric.
    return [g for g in groups.values() if g["sessions"] or g["key_events"]]


def ingest_ga4(db: Session, property_id: int, upload: Upload, data: bytes) -> dict:
    parsed = parse_ga4_csv(data)
    dates: set[date] = {r["date"] for r in parsed.rows}

    # Tier 1 stamping at ingest: rows store the classification as a fact so
    # dashboards and Nora never re-derive it at query time.
    classifier = get_classifier()
    for row in parsed.rows:
        platform = classifier.classify(row["session_source"])
        row["is_ai_referral"] = platform is not None
        row["ai_platform"] = platform
    ai_rows = sum(1 for r in parsed.rows if r["is_ai_referral"])

    replaced = (
        db.query(GA4SessionsDaily)
        .filter(
            GA4SessionsDaily.property_id == property_id,
            GA4SessionsDaily.date.in_(dates),
        )
        .delete(synchronize_session=False)
    )
    db.add_all(
        GA4SessionsDaily(property_id=property_id, upload_id=upload.id, **row)
        for row in parsed.rows
    )
    upload.date_start = min(dates)
    upload.date_end = max(dates)
    summary = {
        "rows_ingested": len(parsed.rows),
        "rows_replaced": replaced,
        "rows_skipped": len(parsed.skipped),
        "skipped": parsed.skipped[:20],
        "date_start": min(dates).isoformat(),
        "date_end": max(dates).isoformat(),
        "ai_rows_detected": ai_rows,
    }
    if parsed.warnings:
        summary["warnings"] = parsed.warnings
    return summary
