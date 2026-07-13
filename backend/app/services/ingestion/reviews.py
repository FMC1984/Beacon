"""Reviews CSV import parser + upsert.

The bridge for getting Google Business Profile reviews (or any provider's) into
Beacon before the live GBP connector is approved for API access. Tolerant like
the other export parsers: it accepts the column names a GBP export or a common
review tool produces and their variants, skips rows with no review text, parses
half-star and worded ratings, and normalizes dates.

Re-imports are idempotent where the data allows it: a row carrying an external
review id updates the matching stored review in place (same dedup key as the
live connector - provider + external_review_id); rows without an id are always
inserted, because a manually captured review has no stable identity to match on.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models import PropertyReview
from app.services.ingestion.common import (
    UploadValidationError,
    parse_export_date,
    read_csv_rows,
)

COLUMN_ALIASES = {
    "review id": "external_review_id",
    "external review id": "external_review_id",
    "id": "external_review_id",
    "reviewer": "author_name",
    "reviewer name": "author_name",
    "author": "author_name",
    "author name": "author_name",
    "name": "author_name",
    "rating": "rating",
    "star rating": "rating",
    "stars": "rating",
    "score": "rating",
    "title": "title",
    "review title": "title",
    "review": "body",
    "review text": "body",
    "body": "body",
    "comment": "body",
    "text": "body",
    "content": "body",
    "date": "review_date",
    "review date": "review_date",
    "create time": "review_date",
    "created": "review_date",
    "response": "response_text",
    "reply": "response_text",
    "response text": "response_text",
    "owner response": "response_text",
    "response date": "response_date",
    "reply date": "response_date",
    "url": "source_url",
    "link": "source_url",
    "source url": "source_url",
    "provider": "provider",
    "source": "provider",
}

_RATING_WORDS = {"one": 1.0, "two": 2.0, "three": 3.0, "four": 4.0, "five": 5.0}


def _parse_rating(raw: str) -> float | None:
    """Tolerant of '5', '5.0', '4,5', 'FIVE', 'five stars', and '★★★★★'.
    Returns None (a real 'no rating'), never 0, when it cannot read a value."""
    raw = (raw or "").strip()
    if not raw:
        return None
    glyphs = raw.count("★")
    if glyphs:
        return float(glyphs)
    cleaned = raw.lower().replace("stars", "").replace("star", "").strip()
    if cleaned in _RATING_WORDS:
        return _RATING_WORDS[cleaned]
    try:
        value = float(cleaned.replace(",", "."))
    except ValueError:
        return None
    return value if 0 <= value <= 5 else None


@dataclass
class ReviewParseResult:
    rows: list[dict] = field(default_factory=list)
    skipped: list[dict] = field(default_factory=list)


def parse_reviews_csv(data: bytes, default_provider: str) -> ReviewParseResult:
    colmap, rows, header_line = read_csv_rows(data, COLUMN_ALIASES)
    if "body" not in colmap:
        raise UploadValidationError(
            "This file has no review text column. Include a column such as "
            "'Review', 'Comment', or 'Body'. Found columns: "
            + ", ".join(sorted(colmap))
            + "."
        )

    def cell(row: dict, key: str) -> str:
        cols = colmap.get(key)
        if not cols:
            return ""
        return (row.get(cols[0]) or "").strip()

    result = ReviewParseResult()
    for i, row in enumerate(rows):
        line_no = header_line + 1 + i
        body = cell(row, "body")
        if not body:
            result.skipped.append({"line": line_no, "reason": "no review text"})
            continue
        result.rows.append(
            {
                "provider": cell(row, "provider") or default_provider,
                "external_review_id": cell(row, "external_review_id") or None,
                "author_name": cell(row, "author_name") or None,
                "rating": _parse_rating(cell(row, "rating")),
                "title": cell(row, "title") or None,
                "body": body,
                "review_date": parse_export_date(cell(row, "review_date")),
                "response_text": cell(row, "response_text") or None,
                "response_date": parse_export_date(cell(row, "response_date")),
                "source_url": cell(row, "source_url") or None,
            }
        )

    if not result.rows:
        raise UploadValidationError("No reviews with text were found in the file.")
    return result


def upsert_reviews(db: Session, property_id: int, rows: list[dict]) -> dict:
    """Insert new reviews; update in place when (provider, external_review_id)
    already exists for the property. Shared shape with the live GBP connector so
    both paths dedup identically. Caller commits and triggers the RAG sync."""
    imported = updated = 0
    for r in rows:
        existing = None
        if r["external_review_id"]:
            existing = (
                db.query(PropertyReview)
                .filter_by(
                    property_id=property_id,
                    provider=r["provider"],
                    external_review_id=r["external_review_id"],
                )
                .one_or_none()
            )
        if existing is not None:
            for field_name, value in r.items():
                setattr(existing, field_name, value)
            existing.updated_at = datetime.now(timezone.utc)
            updated += 1
        else:
            db.add(PropertyReview(property_id=property_id, **r))
            imported += 1
    return {"imported": imported, "updated": updated}


def ingest_reviews(db: Session, property_id: int, data: bytes, default_provider: str) -> dict:
    parsed = parse_reviews_csv(data, default_provider)
    summary = upsert_reviews(db, property_id, parsed.rows)
    summary["skipped"] = len(parsed.skipped)
    summary["skipped_detail"] = parsed.skipped[:20]
    return summary
