"""Paid media export parser + ingester (Google Ads, Meta, other).

ASSUMPTION (flagged per CLAUDE.md): expected file is a daily campaign report
export - Google Ads style (Day, Campaign, Impressions, Clicks, Cost,
Conversions; title preamble and Total rows tolerated) or Meta style (Day,
Campaign name, Impressions, Link clicks, Amount spent (USD), Results). The
platform is supplied by the uploader, not guessed from headers.

Re-uploads replace existing rows for the property AND platform on the covered
dates, so a Google Ads re-export never wipes Meta rows for the same days.
"""

from dataclasses import dataclass, field
from datetime import date

from sqlalchemy.orm import Session

from app.models import PaidMediaDaily, Upload
from app.services.ingestion.common import (
    UploadValidationError,
    parse_export_date,
    parse_float,
    parse_int,
    parse_money,
    read_csv_rows,
)

COLUMN_ALIASES = {
    "day": "date",
    "date": "date",
    "campaign": "campaign",
    "campaign name": "campaign",
    "impressions": "impressions",
    "impr.": "impressions",
    "clicks": "clicks",
    "link clicks": "clicks",
    "cost": "spend",
    "spend": "spend",
    "amount spent": "spend",
    "amount spent (usd)": "spend",
    "cost (usd)": "spend",
    "conversions": "conversions",
    "results": "conversions",
    "conv.": "conversions",
}


@dataclass
class ParseResult:
    rows: list[dict] = field(default_factory=list)
    skipped: list[dict] = field(default_factory=list)


def parse_paid_csv(data: bytes) -> ParseResult:
    colmap, raw_rows, header_line = read_csv_rows(data, COLUMN_ALIASES)

    missing = [
        label
        for key, label in (("date", "Day/Date"), ("campaign", "Campaign"))
        if key not in colmap
    ]
    if missing:
        raise UploadValidationError(
            "Paid media export is missing required columns: "
            + ", ".join(missing)
            + ". Export a daily campaign report."
        )

    def cell(row: dict, key: str) -> str:
        headers = colmap.get(key)
        return (row.get(headers[0]) or "").strip() if headers else ""

    result = ParseResult()
    for line_no, row in enumerate(raw_rows, start=header_line + 1):
        if not any((v or "").strip() for v in row.values()):
            continue
        date_raw = cell(row, "date")
        if date_raw.lower().startswith("total"):
            result.skipped.append({"line": line_no, "reason": "totals row"})
            continue
        parsed_date = parse_export_date(date_raw)
        if parsed_date is None:
            result.skipped.append(
                {"line": line_no, "reason": f"unparseable date '{date_raw}'"}
            )
            continue
        campaign = cell(row, "campaign")
        if not campaign:
            result.skipped.append({"line": line_no, "reason": "empty campaign"})
            continue
        result.rows.append(
            {
                "date": parsed_date,
                "source_line": line_no,
                "campaign_name": campaign,
                "impressions": parse_int(cell(row, "impressions")),
                "clicks": parse_int(cell(row, "clicks")),
                "spend": parse_money(cell(row, "spend")),
                "conversions": parse_float(cell(row, "conversions")),
            }
        )

    if not result.rows:
        raise UploadValidationError("No ingestable data rows found in the file.")
    return result


def ingest_paid(
    db: Session, property_id: int, upload: Upload, data: bytes, platform: str
) -> dict:
    parsed = parse_paid_csv(data)
    dates: set[date] = {r["date"] for r in parsed.rows}

    replaced = (
        db.query(PaidMediaDaily)
        .filter(
            PaidMediaDaily.property_id == property_id,
            PaidMediaDaily.platform == platform,
            PaidMediaDaily.date.in_(dates),
        )
        .delete(synchronize_session=False)
    )
    db.add_all(
        PaidMediaDaily(
            property_id=property_id, upload_id=upload.id, platform=platform, **row
        )
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
    }
