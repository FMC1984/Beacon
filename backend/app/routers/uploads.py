from pathlib import Path

from fastapi import APIRouter, BackgroundTasks, Depends, Form, HTTPException, UploadFile
from sqlalchemy.orm import Session

from app.config import settings
from app.constants import AI_TRAFFIC_DISCLOSURE
from app.db import get_db
from app.models import Property, SourceType, Upload, UploadStatus
from app.schemas.uploads import UploadOut, UploadResult
from app.adapters import ADAPTERS, get_adapter
from app.extensions.hooks import trigger_rag_sync
from app.services.ingestion.common import UploadValidationError
from app.services.ingestion.crm import ingest_crm
from app.services.ingestion.ga4 import ingest_ga4
from app.services.ingestion.ga4_events import ingest_ga4_events
from app.services.ingestion.gbp import ingest_gbp
from app.services.ingestion.gsc import ingest_gsc
from app.services.ingestion.paid import ingest_paid
from app.services.property_types import connector_allowed, label as type_label
from app.services.rag_sync_service import drain_queue

router = APIRouter(prefix="/uploads", tags=["uploads"])

PAID_PLATFORMS = {"google_ads", "meta", "other"}

# Which allowed_connectors key (in property_types.json) each upload source maps
# to. The frontend hides disallowed sources; this is the server-side backstop.
SOURCE_CONNECTOR = {
    SourceType.GA4: "ga4",
    SourceType.GSC: "gsc",
    SourceType.GBP: "gbp",
    SourceType.PAID_MEDIA: "paid",
    SourceType.CRM: "crm",
}


async def run_upload(
    source_type: SourceType,
    ingest_fn,
    property_id: int,
    file: UploadFile,
    db: Session,
    source_account: str | None = None,
    background: BackgroundTasks | None = None,
) -> UploadResult:
    prop = db.get(Property, property_id)
    if prop is None:
        raise HTTPException(status_code=404, detail="Property not found.")

    # This client/site type may not support this data source (e.g. a housing
    # authority has no paid media or CRM). Reject before storing anything.
    connector = SOURCE_CONNECTOR.get(source_type)
    if connector and not connector_allowed(prop.property_type, connector):
        raise HTTPException(
            status_code=422,
            detail=(
                f"{prop.name} is a {type_label(prop.property_type)}, which does "
                f"not support {source_type.value} uploads."
            ),
        )

    data = await file.read()
    upload = Upload(
        source_type=source_type,
        property_id=property_id,
        filename=file.filename or "unnamed.csv",
        source_account=source_account,
        status=UploadStatus.PENDING,
    )
    db.add(upload)
    db.flush()

    # RAG readiness: keep the raw original file (even for failed ingests) so
    # future citations and audits can point at the actual source payload.
    uploads_dir = Path(settings.data_dir) / "uploads"
    uploads_dir.mkdir(parents=True, exist_ok=True)
    stored = uploads_dir / f"{upload.id}_{Path(upload.filename).name}"
    stored.write_bytes(data)
    upload.stored_path = str(stored)

    try:
        summary = ingest_fn(db, property_id, upload, data)
    except UploadValidationError as exc:
        # Keep the failed upload row: bad files must stay visible in history.
        upload.status = UploadStatus.FAILED
        upload.error_message = str(exc)
        db.commit()
        raise HTTPException(status_code=422, detail=str(exc))

    upload.status = UploadStatus.PROCESSED
    upload.row_count = summary["rows_ingested"]
    db.commit()
    if summary.get("ai_rows_detected") is not None:
        summary["disclosure"] = AI_TRAFFIC_DISCLOSURE

    # Queue architecture: enqueue a RAG sync (fast, one row) instead of
    # embedding inline, so the upload response never waits on embeddings. A
    # worker or (when BEACON_RAG_AUTOSYNC is on) a background task drains it.
    job = trigger_rag_sync(
        db,
        property_id=property_id,
        source=source_type.value,
        reason=f"{source_type.value}_import",
    )
    summary["sync_job_id"] = job.id
    if settings.rag_autosync and background is not None:
        background.add_task(drain_queue)

    return UploadResult(
        upload_id=upload.id,
        source_type=source_type,
        status=UploadStatus.PROCESSED,
        **summary,
    )


@router.post("/ga4", response_model=UploadResult, status_code=201)
async def upload_ga4(
    background: BackgroundTasks,
    file: UploadFile,
    property_id: int = Form(...),
    source_account: str | None = Form(None),
    db: Session = Depends(get_db),
):
    return await run_upload(
        SourceType.GA4, ingest_ga4, property_id, file, db, source_account, background
    )


@router.post("/ga4_events", response_model=UploadResult, status_code=201)
async def upload_ga4_events(
    background: BackgroundTasks,
    file: UploadFile,
    property_id: int = Form(...),
    source_account: str | None = Form(None),
    db: Session = Depends(get_db),
):
    return await run_upload(
        SourceType.GA4, ingest_ga4_events, property_id, file, db, source_account, background
    )


@router.post("/gsc", response_model=UploadResult, status_code=201)
async def upload_gsc(
    background: BackgroundTasks,
    file: UploadFile,
    property_id: int = Form(...),
    source_account: str | None = Form(None),
    db: Session = Depends(get_db),
):
    return await run_upload(
        SourceType.GSC, ingest_gsc, property_id, file, db, source_account, background
    )


@router.post("/gbp", response_model=UploadResult, status_code=201)
async def upload_gbp(
    background: BackgroundTasks,
    file: UploadFile,
    property_id: int = Form(...),
    source_account: str | None = Form(None),
    db: Session = Depends(get_db),
):
    return await run_upload(
        SourceType.GBP, ingest_gbp, property_id, file, db, source_account, background
    )


@router.post("/paid_media", response_model=UploadResult, status_code=201)
async def upload_paid_media(
    background: BackgroundTasks,
    file: UploadFile,
    property_id: int = Form(...),
    platform: str = Form(...),
    source_account: str | None = Form(None),
    db: Session = Depends(get_db),
):
    if platform not in PAID_PLATFORMS:
        raise HTTPException(
            status_code=422,
            detail="platform must be one of: " + ", ".join(sorted(PAID_PLATFORMS)),
        )

    def ingest_with_platform(db, property_id, upload, data):
        return ingest_paid(db, property_id, upload, data, platform)

    return await run_upload(
        SourceType.PAID_MEDIA,
        ingest_with_platform,
        property_id,
        file,
        db,
        source_account,
        background,
    )


@router.post("/crm", response_model=UploadResult, status_code=201)
async def upload_crm(
    background: BackgroundTasks,
    file: UploadFile,
    property_id: int = Form(...),
    adapter: str = Form("yardi"),
    source_account: str | None = Form(None),
    db: Session = Depends(get_db),
):
    crm_adapter = get_adapter(adapter)
    if crm_adapter is None:
        raise HTTPException(
            status_code=422,
            detail="Unknown CRM adapter. Available: " + ", ".join(sorted(ADAPTERS)),
        )

    def ingest_with_adapter(db, property_id, upload, data):
        return ingest_crm(db, property_id, upload, data, crm_adapter)

    return await run_upload(
        SourceType.CRM,
        ingest_with_adapter,
        property_id,
        file,
        db,
        source_account,
        background,
    )


@router.get("", response_model=list[UploadOut])
def list_uploads(db: Session = Depends(get_db)):
    return db.query(Upload).order_by(Upload.uploaded_at.desc(), Upload.id.desc()).all()
