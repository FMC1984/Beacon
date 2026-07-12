import enum
from datetime import date, datetime

from sqlalchemy import Date, DateTime, Enum, ForeignKey, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class SourceType(str, enum.Enum):
    GA4 = "ga4"
    GSC = "gsc"
    GBP = "gbp"
    PAID_MEDIA = "paid_media"
    CRM = "crm"


class UploadStatus(str, enum.Enum):
    PENDING = "pending"
    PROCESSED = "processed"
    FAILED = "failed"


def str_enum(enum_cls, name: str) -> Enum:
    return Enum(
        enum_cls,
        name=name,
        native_enum=False,
        values_callable=lambda e: [m.value for m in e],
    )


class Upload(Base):
    __tablename__ = "uploads"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source_type: Mapped[SourceType] = mapped_column(
        str_enum(SourceType, "source_type")
    )
    property_id: Mapped[int | None] = mapped_column(ForeignKey("properties.id"))
    filename: Mapped[str] = mapped_column(String(500))
    # RAG-readiness provenance (PRD 4.7): which account the export came from,
    # the date range it covers, and where the raw original file is kept so a
    # future Nora citation can point at the actual source.
    source_account: Mapped[str | None] = mapped_column(String(300))
    date_start: Mapped[date | None] = mapped_column(Date)
    date_end: Mapped[date | None] = mapped_column(Date)
    stored_path: Mapped[str | None] = mapped_column(String(1000))
    status: Mapped[UploadStatus] = mapped_column(
        str_enum(UploadStatus, "upload_status"), default=UploadStatus.PENDING
    )
    row_count: Mapped[int | None] = mapped_column(Integer)
    error_message: Mapped[str | None] = mapped_column(Text)
    uploaded_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now()
    )
