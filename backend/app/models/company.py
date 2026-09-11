from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class Company(Base):
    """A management company or owner that groups properties. Properties may
    belong to one company or none (company_id nullable = 'Unassigned').
    Company is also the Observatory's Portfolio / Client level; it belongs
    to an Organization (Phase 19), the default one until tenancy exists."""

    __tablename__ = "companies"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(200), unique=True)
    slug: Mapped[str] = mapped_column(String(200), unique=True)
    organization_id: Mapped[int | None] = mapped_column(ForeignKey("organizations.id"))
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now()
    )
