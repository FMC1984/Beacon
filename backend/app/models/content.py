"""Website content storage.

The current source is manual entry / paste through the content endpoints (no
external scraping yet). Content flows into the RAG index via the Phase 9
ContentProvider seam, and the Content Intelligence engine reasons over it.

`mapped_keyword` is the target keyword for the page (the SEO keyword mapping
Beacon already works with); `updated_at` is the freshness signal.
"""

from datetime import datetime

from sqlalchemy import (
    DateTime,
    ForeignKey,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base

# Pages the Content Intelligence engine understands. Content for other page
# names is stored and indexed but not scored as a canonical page.
CANONICAL_PAGES = ("homepage", "amenities", "floor_plans", "neighborhood", "faq")


class PropertyContent(Base):
    __tablename__ = "property_content"
    __table_args__ = (
        UniqueConstraint("property_id", "page", name="uq_content_property_page"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    property_id: Mapped[int] = mapped_column(ForeignKey("properties.id"))
    page: Mapped[str] = mapped_column(String(50))
    title: Mapped[str] = mapped_column(String(300))
    body: Mapped[str] = mapped_column(Text)
    mapped_keyword: Mapped[str | None] = mapped_column(String(300))
    source_url: Mapped[str | None] = mapped_column(String(1000))
    updated_at: Mapped[datetime | None] = mapped_column(DateTime)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now()
    )
