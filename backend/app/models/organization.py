"""Organization: the tenant-ready top of the hierarchy (Phase 19, slice 1b).

    Organization -> Company (portfolio / client) -> Market -> Property

Beacon is single-tenant today: one default organization (slug "default") is
backfilled and every company belongs to it. No user model or per-tenant
auth ships with this; the row exists so budgets, provider rotation,
scheduler overrides and white-label settings have a home, and so every new
Observatory table can carry organization_id from day one.
"""

from datetime import datetime

from sqlalchemy import JSON, Boolean, DateTime, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base

DEFAULT_ORGANIZATION_SLUG = "default"


class Organization(Base):
    __tablename__ = "organizations"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(200))
    slug: Mapped[str] = mapped_column(String(200), unique=True)
    # Free-form, versioned by key: tier, budget {monthly_runs, monthly_usd_cap},
    # provider_rotation, white_label {brand_name, logo_url, primary_domain,
    # accent, report_footer}, scheduler_overrides, alert_thresholds, pricing.
    settings: Mapped[dict | None] = mapped_column(JSON)
    is_active: Mapped[bool] = mapped_column(Boolean, default=True)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
