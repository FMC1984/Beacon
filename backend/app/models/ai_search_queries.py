"""Provider-observed retrieval queries (Phase 19 Observatory).

When an AI platform's API reports the web-search queries it issued while
answering (OpenAI web_search_call actions, Gemini webSearchQueries), Beacon
stores them here verbatim. These are OBSERVED provider behavior for one API
call. They are never consumer search volume, never "AI Mode fan-out", and
every surface that shows them must say so.
"""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class AISearchQuery(Base):
    __tablename__ = "ai_search_queries"
    __table_args__ = (
        Index("ix_ai_search_queries_run", "run_id"),
        Index("ix_ai_search_queries_response", "response_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    response_id: Mapped[int] = mapped_column(ForeignKey("ai_visibility_queries.id"))
    run_id: Mapped[int | None] = mapped_column(ForeignKey("ai_runs.id"))
    provider: Mapped[str] = mapped_column(String(30))
    query_text: Mapped[str] = mapped_column(Text)
    query_order: Mapped[int] = mapped_column(Integer)
    # Which payload field it came from (e.g. "web_search_call.action.query").
    captured_from: Mapped[str] = mapped_column(String(60))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
