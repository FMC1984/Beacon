from datetime import datetime

from sqlalchemy import Boolean, DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class Property(Base):
    __tablename__ = "properties"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(200), unique=True)
    slug: Mapped[str] = mapped_column(String(200), unique=True)
    # Client/site type (multifamily_apartment | housing_authority). Required;
    # existing rows default to multifamily_apartment. Drives terminology, the
    # Content Intelligence knowledge bases, connectors, and Nora framing. This is
    # SEPARATE from PropertyProfile.property_type (regulatory/marketing type).
    property_type: Mapped[str] = mapped_column(
        String(50), nullable=False, server_default="multifamily_apartment"
    )
    # Optional owning company; null means 'Unassigned'.
    company_id: Mapped[int | None] = mapped_column(ForeignKey("companies.id"))
    external_code: Mapped[str | None] = mapped_column(String(100))
    city: Mapped[str | None] = mapped_column(String(100))
    state: Mapped[str | None] = mapped_column(String(2))
    unit_count: Mapped[int | None] = mapped_column(Integer)
    website_url: Mapped[str | None] = mapped_column(String(1000))
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now()
    )
