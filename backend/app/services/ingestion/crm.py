"""CRM export ingester: shared across all CRMAdapters.

Header mapping comes from the adapter's column_aliases; value mapping from the
adapter's normalize(). Unlike the traffic ingesters (replace-on-overlap by
date), CRM leads are entities: rows upsert by (property, external_lead_id), so
re-exports update lead stages in place and never double-count a lead.
"""

from sqlalchemy.orm import Session

from app.adapters.crm_base import CRMAdapter, SkippedRecord
from app.models import CRMLead, Upload
from app.services.ingestion.common import UploadValidationError, read_csv_rows

LEAD_FIELDS = (
    "lead_source_raw",
    "lead_source_normalized",
    "status",
    "first_contact_date",
    "tour_date",
    "application_date",
    "lease_signed_date",
    "move_in_date",
)


def ingest_crm(
    db: Session, property_id: int, upload: Upload, data: bytes, adapter: CRMAdapter
) -> dict:
    try:
        colmap, raw_rows, header_line = read_csv_rows(data, adapter.column_aliases)
    except UploadValidationError as exc:
        raise _with_placeholder_note(adapter, str(exc))

    missing = adapter.missing_columns(colmap)
    if missing:
        raise _with_placeholder_note(
            adapter,
            f"CRM export is missing required columns for the {adapter.label} "
            "adapter: " + ", ".join(missing) + ".",
        )

    inserted = updated = 0
    skipped: list[dict] = []
    seen_ids: dict[str, int] = {}
    contact_dates = []

    for line_no, row in enumerate(raw_rows, start=header_line + 1):
        if not any((v or "").strip() for v in row.values()):
            continue
        record = {
            canonical: (row.get(headers[0]) or "").strip()
            for canonical, headers in colmap.items()
        }
        result = adapter.normalize(record)
        if isinstance(result, SkippedRecord):
            skipped.append({"line": line_no, "reason": result.reason})
            continue
        if result.external_lead_id in seen_ids:
            skipped.append(
                {
                    "line": line_no,
                    "reason": f"duplicate lead id '{result.external_lead_id}' "
                    f"(first seen line {seen_ids[result.external_lead_id]})",
                }
            )
            continue
        seen_ids[result.external_lead_id] = line_no
        contact_dates.append(result.first_contact_date)

        existing = (
            db.query(CRMLead)
            .filter_by(property_id=property_id, external_lead_id=result.external_lead_id)
            .one_or_none()
        )
        if existing:
            for field in LEAD_FIELDS:
                setattr(existing, field, getattr(result, field))
            existing.upload_id = upload.id
            updated += 1
        else:
            db.add(
                CRMLead(
                    property_id=property_id,
                    upload_id=upload.id,
                    external_lead_id=result.external_lead_id,
                    **{f: getattr(result, f) for f in LEAD_FIELDS},
                )
            )
            inserted += 1

    if not inserted and not updated:
        raise UploadValidationError(
            "No ingestable lead records found in the file. Skipped "
            f"{len(skipped)} record(s)."
        )

    upload.date_start = min(contact_dates)
    upload.date_end = max(contact_dates)
    summary = {
        "rows_ingested": inserted,
        "rows_replaced": updated,
        "rows_skipped": len(skipped),
        "skipped": skipped[:20],
        "date_start": min(contact_dates).isoformat(),
        "date_end": max(contact_dates).isoformat(),
    }
    if adapter.is_placeholder:
        from app.adapters.yardi_adapter import PLACEHOLDER_WARNING

        summary["warnings"] = [PLACEHOLDER_WARNING]
    return summary


def _with_placeholder_note(
    adapter: CRMAdapter, message: str
) -> UploadValidationError:
    if adapter.is_placeholder:
        from app.adapters.yardi_adapter import PLACEHOLDER_WARNING

        message = f"{message} NOTE: {PLACEHOLDER_WARNING}"
    return UploadValidationError(message)
