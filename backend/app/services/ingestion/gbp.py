"""Google Business Profile performance export parser + ingester.

ASSUMPTION (flagged per CLAUDE.md): GBP export column names vary by export
vintage, so this parser maps known aliases onto Beacon's five normalized
metrics and reports any column it cannot place (unmapped_columns in the upload
result) instead of silently dropping data. Metrics split across Desktop/Mobile
columns are summed. One row per date is required; files with duplicate dates
(e.g. multi-location bulk exports) are rejected rather than silently mixed.

Re-uploads replace existing GBP rows for the property on the covered dates.
"""

from dataclasses import dataclass, field
from datetime import date

from sqlalchemy.orm import Session

from app.models import GBPMetricsDaily, Upload
from app.services.ingestion.common import (
    UploadValidationError,
    normalize_header,
    parse_export_date,
    parse_int,
    read_csv_rows,
)

METRIC_KEYS = (
    "search_impressions",
    "maps_impressions",
    "website_clicks",
    "calls",
    "direction_requests",
)

COLUMN_ALIASES = {
    "date": "date",
    # search impressions (desktop/mobile variants get summed)
    "google search impressions": "search_impressions",
    "search impressions": "search_impressions",
    "searches": "search_impressions",
    "google search - desktop": "search_impressions",
    "google search - mobile": "search_impressions",
    "impressions - google search": "search_impressions",
    # maps impressions
    "google maps impressions": "maps_impressions",
    "maps impressions": "maps_impressions",
    "google maps - desktop": "maps_impressions",
    "google maps - mobile": "maps_impressions",
    "impressions - google maps": "maps_impressions",
    # website clicks
    "website clicks": "website_clicks",
    "website visits": "website_clicks",
    "clicks to website": "website_clicks",
    # calls
    "calls": "calls",
    "phone calls": "calls",
    "calls made": "calls",
    # direction requests
    "direction requests": "direction_requests",
    "directions": "direction_requests",
    "directions requests": "direction_requests",
}


@dataclass
class ParseResult:
    rows: list[dict] = field(default_factory=list)
    skipped: list[dict] = field(default_factory=list)
    unmapped_columns: list[str] = field(default_factory=list)


def parse_gbp_csv(data: bytes) -> ParseResult:
    colmap, raw_rows, header_line = read_csv_rows(data, COLUMN_ALIASES)

    if "date" not in colmap:
        raise UploadValidationError(
            "GBP export has no Date column. Export the daily performance report "
            "for a single location. Found columns: " + ", ".join(sorted(colmap)) + "."
        )
    mapped_metrics = [k for k in METRIC_KEYS if k in colmap]
    if not mapped_metrics:
        raise UploadValidationError(
            "GBP export has no recognizable metric columns. Expected headers "
            "like: Google Search impressions, Google Maps impressions, Website "
            "clicks, Calls, Direction requests."
        )

    result = ParseResult()
    if raw_rows:
        mapped_headers = {h for headers in colmap.values() for h in headers}
        result.unmapped_columns = [
            h for h in raw_rows[0].keys() if h and h not in mapped_headers
        ]

    seen_dates: dict[date, int] = {}
    for line_no, row in enumerate(raw_rows, start=header_line + 1):
        if not any((v or "").strip() for v in row.values()):
            continue
        date_cell = (row.get(colmap["date"][0]) or "").strip()
        parsed_date = parse_export_date(date_cell)
        if parsed_date is None:
            result.skipped.append(
                {"line": line_no, "reason": f"unparseable date '{date_cell}'"}
            )
            continue
        if parsed_date in seen_dates:
            raise UploadValidationError(
                f"Multiple rows for {parsed_date.isoformat()} (lines "
                f"{seen_dates[parsed_date]} and {line_no}). GBP files must be "
                "single-location daily exports; bulk multi-location exports "
                "cannot be ingested."
            )
        seen_dates[parsed_date] = line_no

        record = {"date": parsed_date, "source_line": line_no}
        for key in mapped_metrics:
            record[key] = sum(parse_int(row.get(h) or "") for h in colmap[key])
        result.rows.append(record)

    if not result.rows:
        raise UploadValidationError("No ingestable data rows found in the file.")
    return result


def ingest_gbp(db: Session, property_id: int, upload: Upload, data: bytes) -> dict:
    parsed = parse_gbp_csv(data)
    dates: set[date] = {r["date"] for r in parsed.rows}

    replaced = (
        db.query(GBPMetricsDaily)
        .filter(
            GBPMetricsDaily.property_id == property_id,
            GBPMetricsDaily.date.in_(dates),
        )
        .delete(synchronize_session=False)
    )
    db.add_all(
        GBPMetricsDaily(property_id=property_id, upload_id=upload.id, **row)
        for row in parsed.rows
    )
    upload.date_start = min(dates)
    upload.date_end = max(dates)
    return {
        "rows_ingested": len(parsed.rows),
        "rows_replaced": replaced,
        "rows_skipped": len(parsed.skipped),
        "skipped": parsed.skipped[:20],
        "date_start": min(dates).isoformat(),
        "date_end": max(dates).isoformat(),
        "unmapped_columns": parsed.unmapped_columns or None,
    }
