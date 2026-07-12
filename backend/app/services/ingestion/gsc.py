"""Google Search Console export parser + ingester.

Two shapes are accepted:

1. The Dates tab of a GSC Performance export (Date, Clicks, Impressions, CTR,
   Position), optionally with a Query or Page column when the file came from
   the API. Stored at a true daily grain.
2. The UI's Queries.csv / Pages.csv, which has no Date column at all - Search
   Console's own UI cannot export Query + Date together in one file (an actual
   product limitation, not a user mistake). These are accepted as a PERIOD
   SNAPSHOT: every row is stamped with the export's covered end date (read
   from the '# Start date: YYYYMMDD' / '# End date: YYYYMMDD' preamble Google
   includes in these files), never faked as daily. The ingest response and
   upload warnings say plainly that the rows are a period total, not daily.

Re-uploads replace existing rows for the property on the dates/period the file
covers, so a re-export of a corrected range is safe. Snapshot re-uploads only
replace prior snapshot rows (query/page not null) on the same end date, so
they never clobber true daily Dates-tab rows landing on that same calendar
date.
"""

from dataclasses import dataclass, field
from datetime import date

from sqlalchemy.orm import Session

from app.models import GSCPerformanceDaily, Upload
from app.services.ingestion.common import (
    UploadValidationError,
    parse_ctr,
    parse_export_date,
    parse_float,
    parse_int,
    parse_preamble_date_range,
    read_csv_rows,
)

COLUMN_ALIASES = {
    "date": "date",
    "top queries": "query",
    "query": "query",
    "queries": "query",
    # GA4's own "Reports > Search Console" panel prefixes every column with
    # "Organic Google Search" instead of using Search Console's own naming.
    "organic google search query": "query",
    "top pages": "page",
    "page": "page",
    "pages": "page",
    "organic google search page": "page",
    "organic google search landing page": "page",
    "clicks": "clicks",
    "organic google search clicks": "clicks",
    "impressions": "impressions",
    "organic google search impressions": "impressions",
    "ctr": "ctr",
    "organic google search click through rate": "ctr",
    "position": "position",
    "average position": "position",
    "organic google search average position": "position",
}


@dataclass
class ParseResult:
    rows: list[dict] = field(default_factory=list)
    skipped: list[dict] = field(default_factory=list)
    # Set when the file had no Date column and was accepted as a period
    # snapshot instead; (start, end) is the true covered range, read from the
    # file's own preamble. Every row's stored `date` is snapshot_period[1].
    snapshot_period: tuple[date, date] | None = None


def parse_gsc_csv(data: bytes) -> ParseResult:
    colmap, raw_rows, header_line = read_csv_rows(data, COLUMN_ALIASES)

    snapshot_period = None
    if "date" not in colmap:
        if "query" not in colmap and "page" not in colmap:
            raise UploadValidationError(
                "GSC export has no Date column. Export the Dates tab of the "
                "Performance report, or a Queries/Pages export (Google cannot "
                "export Query + Date together). Found columns: "
                + ", ".join(sorted(colmap))
                + "."
            )
        snapshot_period = parse_preamble_date_range(data)
        if snapshot_period is None:
            raise UploadValidationError(
                "GSC export has no Date column, and this file's covered period "
                "could not be determined (no 'Start date' / 'End date' header "
                "lines found). Export the Dates tab instead, or use a file with "
                "the standard Google header comments."
            )

    missing = [c for c in ("clicks", "impressions") if c not in colmap]
    if missing:
        raise UploadValidationError(
            "GSC export is missing required columns: "
            + ", ".join(m.title() for m in missing)
            + "."
        )

    def cell(row: dict, key: str) -> str:
        headers = colmap.get(key)
        return (row.get(headers[0]) or "").strip() if headers else ""

    result = ParseResult(snapshot_period=snapshot_period)
    for line_no, row in enumerate(raw_rows, start=header_line + 1):
        if not any((v or "").strip() for v in row.values()):
            continue
        if snapshot_period is not None:
            parsed_date = snapshot_period[1]
        else:
            parsed_date = parse_export_date(cell(row, "date"))
            if parsed_date is None:
                result.skipped.append(
                    {"line": line_no, "reason": f"unparseable date '{cell(row, 'date')}'"}
                )
                continue
        result.rows.append(
            {
                "date": parsed_date,
                "source_line": line_no,
                "query": cell(row, "query") or None,
                "page": cell(row, "page") or None,
                "clicks": parse_int(cell(row, "clicks")),
                "impressions": parse_int(cell(row, "impressions")),
                "ctr": parse_ctr(cell(row, "ctr")),
                "position": parse_float(cell(row, "position")),
            }
        )

    if not result.rows:
        raise UploadValidationError("No ingestable data rows found in the file.")
    return result


def ingest_gsc(db: Session, property_id: int, upload: Upload, data: bytes) -> dict:
    parsed = parse_gsc_csv(data)

    if parsed.snapshot_period is not None:
        date_start, date_end = parsed.snapshot_period
        # Scoped to prior snapshot rows only (query/page not null), so this
        # never deletes true daily Dates-tab rows landing on the same date.
        replaced = (
            db.query(GSCPerformanceDaily)
            .filter(
                GSCPerformanceDaily.property_id == property_id,
                GSCPerformanceDaily.date == date_end,
                GSCPerformanceDaily.query.isnot(None),
            )
            .delete(synchronize_session=False)
        )
    else:
        dates: set[date] = {r["date"] for r in parsed.rows}
        date_start, date_end = min(dates), max(dates)
        replaced = (
            db.query(GSCPerformanceDaily)
            .filter(
                GSCPerformanceDaily.property_id == property_id,
                GSCPerformanceDaily.date.in_(dates),
            )
            .delete(synchronize_session=False)
        )

    db.add_all(
        GSCPerformanceDaily(property_id=property_id, upload_id=upload.id, **row)
        for row in parsed.rows
    )
    upload.date_start = date_start
    upload.date_end = date_end
    summary = {
        "rows_ingested": len(parsed.rows),
        "rows_replaced": replaced,
        "rows_skipped": len(parsed.skipped),
        "skipped": parsed.skipped[:20],
        "date_start": date_start.isoformat(),
        "date_end": date_end.isoformat(),
    }
    if parsed.snapshot_period is not None:
        summary["warnings"] = [
            f"This file has no daily Date column, so it was stored as one "
            f"period total for {date_start.isoformat()} to {date_end.isoformat()}"
            f", not day-by-day. Query/keyword totals reflect the whole period."
        ]
    return summary
