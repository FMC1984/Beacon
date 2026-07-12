import enum
from datetime import date, datetime

from sqlalchemy import JSON, Date, DateTime, ForeignKey, Integer, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models.uploads import str_enum


class ReportType(str, enum.Enum):
    WEEKLY = "weekly"
    MONTHLY = "monthly"
    QUARTERLY = "quarterly"
    EXECUTIVE = "executive"


class Report(Base):
    __tablename__ = "reports"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    report_type: Mapped[ReportType] = mapped_column(
        str_enum(ReportType, "report_type")
    )
    # Null property means a portfolio-level report.
    property_id: Mapped[int | None] = mapped_column(ForeignKey("properties.id"))
    period_start: Mapped[date] = mapped_column(Date)
    period_end: Mapped[date] = mapped_column(Date)
    content_md: Mapped[str] = mapped_column(Text)
    citations: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now()
    )
