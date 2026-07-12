import enum
from datetime import date

from sqlalchemy import (
    CheckConstraint,
    Date,
    ForeignKey,
    Index,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models.uploads import str_enum


class LeadStatus(str, enum.Enum):
    LEAD = "lead"
    TOUR = "tour"
    APPLICATION = "application"
    LEASE = "lease"
    LOST = "lost"


class CRMLead(Base):
    """Normalized lead row. Populated only through a CRMAdapter (Phase 5) so
    source-CRM quirks stay in the adapter layer."""

    __tablename__ = "crm_leads"
    __table_args__ = (
        UniqueConstraint(
            "property_id", "external_lead_id", name="uq_lead_property_external"
        ),
        Index("ix_lead_property_contact", "property_id", "first_contact_date"),
        Index("ix_lead_property_lease", "property_id", "lease_signed_date"),
        CheckConstraint(
            "upload_id IS NOT NULL OR sync_job_id IS NOT NULL",
            name="ck_crm_leads_provenance",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    property_id: Mapped[int] = mapped_column(ForeignKey("properties.id"))
    upload_id: Mapped[int | None] = mapped_column(ForeignKey("uploads.id"))
    sync_job_id: Mapped[int | None] = mapped_column(ForeignKey("sync_jobs.id"))
    external_lead_id: Mapped[str] = mapped_column(String(100))
    lead_source_raw: Mapped[str] = mapped_column(String(300))
    lead_source_normalized: Mapped[str | None] = mapped_column(String(100))
    status: Mapped[LeadStatus] = mapped_column(str_enum(LeadStatus, "lead_status"))
    first_contact_date: Mapped[date] = mapped_column(Date)
    tour_date: Mapped[date | None] = mapped_column(Date)
    application_date: Mapped[date | None] = mapped_column(Date)
    lease_signed_date: Mapped[date | None] = mapped_column(Date)
    move_in_date: Mapped[date | None] = mapped_column(Date)
