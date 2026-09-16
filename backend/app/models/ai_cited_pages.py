"""Cache of pages AI answers cite (Phase 19).

"Mentioned on page" asks whether a cited page actually names the property.
Answering it means fetching the page, which is slow, costs the other site a
request, and may fail. So each URL is fetched at most once per cache window
and the result is stored here; the mention check itself is a deterministic
text match over the stored body and can be re-run for any property without
another fetch.

A row is one URL, not one (URL, property): the same directory page is
checked for every property that was cited alongside it.
"""

from datetime import datetime

from sqlalchemy import DateTime, Index, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base

CHECK_OK = "ok"
CHECK_UNREACHABLE = "unreachable"
CHECK_BLOCKED = "blocked"  # 4xx: bots refused, or the page is gone
CHECK_NOT_HTML = "not_html"

# Fetch again after this many days so a page that starts naming the
# property does not stay "not mentioned" forever.
RECHECK_AFTER_DAYS = 14


class AICitedPage(Base):
    __tablename__ = "ai_cited_pages"
    __table_args__ = (
        Index("uq_ai_cited_pages_url", "normalized_url", unique=True),
        Index("ix_ai_cited_pages_fetched", "fetched_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    normalized_url: Mapped[str] = mapped_column(String(1000))
    url: Mapped[str] = mapped_column(String(2000))
    domain: Mapped[str] = mapped_column(String(255))
    fetched_at: Mapped[datetime] = mapped_column(DateTime)
    status: Mapped[str] = mapped_column(String(20))
    http_status: Mapped[int | None] = mapped_column(Integer)
    error: Mapped[str | None] = mapped_column(Text)
    title: Mapped[str | None] = mapped_column(String(500))
    # Visible text, capped by the fetcher; the mention check runs over this.
    body: Mapped[str | None] = mapped_column(Text)
    char_count: Mapped[int] = mapped_column(Integer, default=0)
    # "fetch" for a real request, "sample" for rows the demo seeder wrote.
    source: Mapped[str] = mapped_column(String(20), default="fetch")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
