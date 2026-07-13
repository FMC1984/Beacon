"""GA4 events export parser + ingester.

Parses GA4's Events report (event name, event count, total users). Tolerant of
the two shapes that export takes: one with a per-row Date dimension, and the
common aggregate one that has no Date column but carries the report's date range
in the '# Start date / # End date' preamble. When only the range is present,
every event is stamped at the range end date (a single representative day),
which is enough for the windowed event breakdowns on the Dashboard and SEO
report; the limitation is disclosed in the upload warning.

Re-uploads are idempotent by replacement, like the other GA4 parsers: existing
event rows for the property and the set of dates in the file are deleted before
insert.
"""

from dataclasses import dataclass, field
from datetime import date

from sqlalchemy.orm import Session

from app.models import GA4EventsDaily, Upload
from app.services.ingestion.common import (
    UploadValidationError,
    parse_export_date,
    parse_int,
    parse_preamble_date_range,
    read_csv_rows,
)

COLUMN_ALIASES = {
    "date": "date",
    "event name": "event_name",
    "event": "event_name",
    "name": "event_name",
    "event count": "event_count",
    "count": "event_count",
    "events": "event_count",
    "total users": "total_users",
    "users": "total_users",
    "active users": "total_users",
}

TOTALS_MARKERS = ("grand total", "total", "totals")


@dataclass
class ParseResult:
    rows: list[dict] = field(default_factory=list)
    skipped: list[dict] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)


def parse_ga4_events_csv(data: bytes) -> ParseResult:
    colmap, rows, header_line = read_csv_rows(data, COLUMN_ALIASES)
    if "event_name" not in colmap or "event_count" not in colmap:
        raise UploadValidationError(
            "This GA4 events export needs an 'Event name' and an 'Event count' "
            "column. Found columns: " + ", ".join(sorted(colmap)) + "."
        )

    result = ParseResult()
    has_date = "date" in colmap
    fallback_date: date | None = None
    if not has_date:
        rng = parse_preamble_date_range(data)
        if rng is None:
            raise UploadValidationError(
                "This events export has no Date column and no date range in its "
                "header, so Beacon cannot place it in time. Re-export it with the "
                "Date dimension added, or keep the report's date-range header."
            )
        fallback_date = rng[1]
        result.warnings.append(
            "This export has no per-day breakdown, so all event counts are "
            f"recorded on {fallback_date.isoformat()} (the end of the report's "
            "date range)."
        )

    def cell(row: dict, key: str) -> str:
        cols = colmap.get(key)
        if not cols:
            return ""
        return (row.get(cols[0]) or "").strip()

    for i, row in enumerate(rows):
        line_no = header_line + 1 + i
        name = cell(row, "event_name")
        if not name or name.lower() in TOTALS_MARKERS:
            result.skipped.append({"line": line_no, "reason": "no event name or totals row"})
            continue
        if has_date:
            d = parse_export_date(cell(row, "date"))
        else:
            d = fallback_date
        if d is None:
            result.skipped.append({"line": line_no, "reason": "unparseable date"})
            continue
        result.rows.append(
            {
                "date": d,
                "source_line": line_no,
                "event_name": name,
                "event_count": parse_int(cell(row, "event_count")),
                "total_users": parse_int(cell(row, "total_users")),
            }
        )

    if not result.rows:
        raise UploadValidationError("No event rows found in the file.")
    return result


def ingest_ga4_events(db: Session, property_id: int, upload: Upload, data: bytes) -> dict:
    parsed = parse_ga4_events_csv(data)
    dates = {r["date"] for r in parsed.rows}

    replaced = (
        db.query(GA4EventsDaily)
        .filter(
            GA4EventsDaily.property_id == property_id,
            GA4EventsDaily.date.in_(dates),
        )
        .delete(synchronize_session=False)
    )
    db.add_all(
        GA4EventsDaily(property_id=property_id, upload_id=upload.id, **row)
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
    }
    if parsed.warnings:
        summary["warnings"] = parsed.warnings
    return summary
