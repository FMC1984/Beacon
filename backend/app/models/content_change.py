"""Content change log (Phase 16F).

An operator-recorded record of a website or optimization change, so Beacon can
show performance around the change date. Recording a change never implies
Beacon caused or measured causation; the Content Impact report attaches the
mandatory external-factors caveat to every before-and-after view.
"""

import enum
from datetime import date, datetime

from sqlalchemy import Date, DateTime, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base
from app.models.uploads import str_enum


class ChangeType(str, enum.Enum):
    NEW_PAGE = "new_page"
    EXPANDED_CONTENT = "expanded_content"
    FAQ_UPDATE = "faq_update"
    METADATA_UPDATE = "metadata_update"
    INTERNAL_LINK_UPDATE = "internal_link_update"
    STRUCTURED_DATA_UPDATE = "structured_data_update"
    TECHNICAL_CORRECTION = "technical_correction"
    OTHER = "other"


class ContentChange(Base):
    __tablename__ = "content_changes"
    __table_args__ = (
        Index("ix_content_change_property_date", "property_id", "date_implemented"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    property_id: Mapped[int] = mapped_column(ForeignKey("properties.id"))
    # Denormalized company for portfolio-scoped queries; nullable like Property.
    company_id: Mapped[int | None] = mapped_column(ForeignKey("companies.id"))
    page_url: Mapped[str | None] = mapped_column(String(1000))
    change_title: Mapped[str] = mapped_column(String(300))
    change_type: Mapped[ChangeType] = mapped_column(
        str_enum(ChangeType, "content_change_type")
    )
    date_implemented: Mapped[date] = mapped_column(Date)
    notes: Mapped[str | None] = mapped_column(Text)
    # Free text: opportunities are computed, not persisted as rows, so a change
    # references one by title/description rather than a foreign key.
    related_opportunity: Mapped[str | None] = mapped_column(String(500))
    created_by: Mapped[str | None] = mapped_column(String(200))
    before_snapshot_ref: Mapped[str | None] = mapped_column(String(500))
    after_snapshot_ref: Mapped[str | None] = mapped_column(String(500))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
