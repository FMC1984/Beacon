from datetime import date, datetime

from pydantic import BaseModel, ConfigDict

from app.models import SourceType, UploadStatus


class SkippedRow(BaseModel):
    line: int
    reason: str


class UploadResult(BaseModel):
    upload_id: int
    source_type: SourceType
    status: UploadStatus
    rows_ingested: int
    rows_replaced: int
    rows_skipped: int
    skipped: list[SkippedRow]
    date_start: str
    date_end: str
    # Present whenever the ingest classified AI referrals. Any AI traffic
    # number must travel with the disclosure (CLAUDE.md hard rule 3); the
    # router sets it whenever ai_rows_detected is not None.
    ai_rows_detected: int | None = None
    disclosure: str | None = None
    # GBP only: source columns the parser could not place (surfaced, not dropped).
    unmapped_columns: list[str] | None = None
    # e.g. the Yardi placeholder-mapping warning; never silently absent.
    warnings: list[str] | None = None
    # The RAG sync job enqueued for this upload (Phase 9). Embeddings run in the
    # background; the upload response does not wait on them.
    sync_job_id: int | None = None


class UploadOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    source_type: SourceType
    property_id: int | None
    filename: str
    source_account: str | None
    date_start: date | None
    date_end: date | None
    stored_path: str | None
    status: UploadStatus
    row_count: int | None
    error_message: str | None
    uploaded_at: datetime
