"""AI readability checks (competitive roadmap 6, v1: raw HTML only).

What a simple crawler receives from the property's own site, without running
JavaScript: which renter facts appear in the initial HTML, whether robots.txt
admits the AI crawlers, and what structured data is declared. One row per
check; the latest row is the report. Rendered-vs-raw comparison is a later
version and needs a headless browser.
"""

from datetime import datetime

from sqlalchemy import JSON, DateTime, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class AIReadabilityCheck(Base):
    __tablename__ = "ai_readability_checks"
    __table_args__ = (Index("ix_ai_readability_property_checked", "property_id", "checked_at"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organization_id: Mapped[int | None] = mapped_column(Integer)
    property_id: Mapped[int] = mapped_column(ForeignKey("properties.id"))
    checked_at: Mapped[datetime] = mapped_column(DateTime)
    site_url: Mapped[str] = mapped_column(String(1000))
    status: Mapped[str] = mapped_column(String(20))  # ok | error
    error: Mapped[str | None] = mapped_column(Text)
    pages: Mapped[list | None] = mapped_column(JSON)          # [{url, http_status, chars, scripts, found:{cat: snippet}}]
    categories: Mapped[dict | None] = mapped_column(JSON)     # {cat: {present, page, evidence}}
    robots: Mapped[dict | None] = mapped_column(JSON)         # {reachable, url, agents:{name: allowed|disallowed|unknown}}
    structured_data: Mapped[list | None] = mapped_column(JSON)  # JSON-LD @type values seen
    findings: Mapped[list | None] = mapped_column(JSON)       # [{severity, category, text}]
    source: Mapped[str] = mapped_column(String(20), default="fetch")  # fetch | sample
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
