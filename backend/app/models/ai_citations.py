"""Structured citations per stored AI response (Phase 19 Observatory).

One row per source the provider reported (or, for providers that expose no
citation payload, per URL Beacon found in the prose - capture_method says
which). Replaces nothing: AIVisibilityQuery.sources_cited keeps its
domain-only list for the legacy GEO/SoV readers; this table carries the
full URL, position, and classification so citation rate, citation share and
source influence can be computed and audited.
"""

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base

CAPTURE_PROVIDER_ANNOTATION = "provider_annotation"
CAPTURE_GROUNDING_CHUNK = "grounding_chunk"
CAPTURE_PROSE_REGEX = "prose_regex"
CAPTURE_DEMO = "demo"


class AICitation(Base):
    __tablename__ = "ai_citations"
    __table_args__ = (
        Index("ix_ai_citations_response", "response_id"),
        Index("ix_ai_citations_run", "run_id"),
        Index("ix_ai_citations_domain", "domain"),
        Index("ix_ai_citations_market_domain", "market_id", "domain"),
        Index(
            "uq_ai_citations_response_url_order",
            "response_id", "normalized_url", "citation_order", unique=True,
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    response_id: Mapped[int] = mapped_column(ForeignKey("ai_visibility_queries.id"))
    run_id: Mapped[int | None] = mapped_column(ForeignKey("ai_runs.id"))
    organization_id: Mapped[int | None] = mapped_column(Integer)
    market_id: Mapped[int | None] = mapped_column(Integer)
    url: Mapped[str] = mapped_column(Text)
    normalized_url: Mapped[str] = mapped_column(Text)
    domain: Mapped[str] = mapped_column(String(255))
    root_domain: Mapped[str] = mapped_column(String(255))
    path: Mapped[str | None] = mapped_column(String(500))
    title: Mapped[str | None] = mapped_column(String(500))
    citation_order: Mapped[int] = mapped_column(Integer)
    # Character offsets in the response text when the provider reports them.
    citation_position: Mapped[int | None] = mapped_column(Integer)
    end_position: Mapped[int | None] = mapped_column(Integer)
    # owned | competitor | government | directory | review_platform | media | unknown
    source_type: Mapped[str] = mapped_column(String(30))
    capture_method: Mapped[str] = mapped_column(String(30))
    # For providers that hand back redirect URLs (Gemini grounding), the
    # resolved destination; None until resolved (domain then UNAVAILABLE).
    resolved_url: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
