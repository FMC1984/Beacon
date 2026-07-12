from datetime import date, datetime

from sqlalchemy import JSON, Date, DateTime, ForeignKey, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base


class RAGChunk(Base):
    """Provenance registry for ChromaDB chunks. Vectors and chunk text live in
    Chroma; this table is what lets a citation resolve back to real source rows."""

    __tablename__ = "rag_chunks"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    chroma_id: Mapped[str] = mapped_column(String(100), unique=True)
    property_id: Mapped[int | None] = mapped_column(ForeignKey("properties.id"))
    source_table: Mapped[str] = mapped_column(String(100))
    source_ref: Mapped[str] = mapped_column(String(500))
    period_start: Mapped[date | None] = mapped_column(Date)
    period_end: Mapped[date | None] = mapped_column(Date)
    # SHA-256 of the chunk text; lets the indexer skip re-embedding unchanged
    # chunks on rebuild.
    text_hash: Mapped[str | None] = mapped_column(String(64))
    # Expanded registry (Phase 9): logical source (ga4/gsc/gbp/paid_media/crm/
    # content) distinct from the source_table, the content page when applicable,
    # and the embedding lineage so a stale or mis-provider'd chunk is debuggable
    # and the sync service can detect provider/version changes.
    source: Mapped[str | None] = mapped_column(String(50))
    page: Mapped[str | None] = mapped_column(String(100))
    embedding_version: Mapped[str | None] = mapped_column(String(100))
    provider: Mapped[str | None] = mapped_column(String(50))
    updated_at: Mapped[datetime | None] = mapped_column(DateTime)
    # Semantic enrichment (Phase 15a): deterministic topics/entities/intents/
    # per-topic sentiment/normalized terms computed at index time. Metadata
    # only; never a substitute for the chunk text. Null = indexed before
    # enrichment existed (filled on next sync).
    enrichment: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now()
    )
