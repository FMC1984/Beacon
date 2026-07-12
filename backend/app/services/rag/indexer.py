"""Incremental index core + full rebuild.

`apply_chunk_sync` is the shared engine used by both the full `build_index`
(CLI / admin rebuild) and the scoped `rag_sync_service` jobs. A chunk is
re-embedded only when its text changed OR the embedding provider/version
changed; unchanged chunks keep their vectors. Chunks whose source data
disappeared are removed from Chroma and the registry.

Because a provider/version change makes every chunk's stored embedding_version
differ, it forces a full re-embed automatically, and the Chroma collection is
keyed by provider so switching providers starts from a clean vector space.
"""

import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

from sqlalchemy.orm import Session

from app.config import settings
from app.connectors.development import DevelopmentDataProvider
from app.models import RAGChunk
from app.providers.base import EmbeddingProvider
from app.services.rag.chunker import Chunk, build_chunks
from app.services.rag.store import get_collection
from app.services.semantic import enrich_text, property_entity_names

STATE_FILENAME = "last_index.json"


@dataclass
class SyncCounts:
    chunks_total: int
    embedded: int
    unchanged: int
    removed: int


def last_index_state(chroma_dir: str | None = None) -> dict | None:
    path = Path(chroma_dir or settings.chroma_dir) / STATE_FILENAME
    if not path.exists():
        return None
    return json.loads(path.read_text())


def _needs_embed(row: RAGChunk | None, chunk: Chunk, provider: EmbeddingProvider) -> bool:
    if row is None:
        return True
    return (
        row.text_hash != chunk.text_hash
        or row.embedding_version != provider.version
        or row.provider != provider.name
    )


def _iso(value) -> str:
    return value.isoformat() if value else ""


def _chunk_metadata(chunk: Chunk, enrichment: dict) -> dict:
    """Chroma metadata for one chunk. Chroma values must be scalars, so topics
    become per-topic booleans (filterable with where={'topic_x': True}) and
    list fields are comma-joined; the full structured enrichment lives in the
    rag_chunks registry."""
    meta = {
        "property_id": chunk.property_id if chunk.property_id is not None else -1,
        "source": chunk.source,
        "source_table": chunk.source_table,
        "page": chunk.page or "",
        "period_start": _iso(chunk.period_start),
        "period_end": _iso(chunk.period_end),
        "intents": ",".join(enrichment["intents"]),
        "entities": ",".join(e["value"] for e in enrichment["entities"]),
        "normalized_terms": ",".join(enrichment["normalized_terms"]),
    }
    for topic in enrichment["topics"]:
        meta[f"topic_{topic}"] = True
    return meta


def _enrich_chunks(db: Session, chunks: list[Chunk]) -> dict[str, dict]:
    """Deterministic semantic enrichment per chunk (chroma_id -> enrichment).
    Cheap (no model calls), so it runs for every chunk in scope on every sync;
    a taxonomy edit therefore refreshes metadata even when text is unchanged."""
    names_cache: dict[int, dict] = {}
    out: dict[str, dict] = {}
    for c in chunks:
        if c.property_id not in names_cache:
            names_cache[c.property_id] = property_entity_names(db, c.property_id)
        out[c.chroma_id] = enrich_text(c.text, extra_entities=names_cache[c.property_id])
    return out


def apply_chunk_sync(
    db: Session,
    provider: EmbeddingProvider,
    chunks: list[Chunk],
    scope_rows: list[RAGChunk],
    chroma_dir: str | None = None,
) -> SyncCounts:
    """Reconcile `chunks` against `scope_rows` (the registry rows in this
    scope) and the Chroma collection. Only touches ids within the given chunks
    and scope_rows, so a scoped call never disturbs other properties."""
    now = datetime.now(timezone.utc)
    collection = get_collection(chroma_dir, provider.key)
    registry = {row.chroma_id: row for row in scope_rows}
    enrichments = _enrich_chunks(db, chunks)

    to_embed = [c for c in chunks if _needs_embed(registry.get(c.chroma_id), c, provider)]
    unchanged = len(chunks) - len(to_embed)

    if to_embed:
        vectors = provider.embed([c.text for c in to_embed])
        collection.upsert(
            ids=[c.chroma_id for c in to_embed],
            embeddings=vectors,
            documents=[c.text for c in to_embed],
            metadatas=[_chunk_metadata(c, enrichments[c.chroma_id]) for c in to_embed],
        )
        for chunk in to_embed:
            row = registry.get(chunk.chroma_id)
            if row is None:
                row = RAGChunk(chroma_id=chunk.chroma_id)
                db.add(row)
            row.property_id = chunk.property_id
            row.source = chunk.source
            row.source_table = chunk.source_table
            row.source_ref = chunk.source_ref
            row.page = chunk.page
            row.period_start = chunk.period_start
            row.period_end = chunk.period_end
            row.text_hash = chunk.text_hash
            row.provider = provider.name
            row.embedding_version = provider.version
            row.enrichment = enrichments[chunk.chroma_id]
            row.updated_at = now

    # Refresh metadata on unchanged chunks whose enrichment drifted (taxonomy
    # edits change metadata without changing text; enrichment is deterministic,
    # so this is a no-op on ordinary re-syncs).
    embedded_ids = {c.chroma_id for c in to_embed}
    stale_meta = [
        c
        for c in chunks
        if c.chroma_id not in embedded_ids
        and registry.get(c.chroma_id) is not None
        and registry[c.chroma_id].enrichment != enrichments[c.chroma_id]
    ]
    if stale_meta:
        collection.update(
            ids=[c.chroma_id for c in stale_meta],
            metadatas=[_chunk_metadata(c, enrichments[c.chroma_id]) for c in stale_meta],
        )
        for chunk in stale_meta:
            registry[chunk.chroma_id].enrichment = enrichments[chunk.chroma_id]
            registry[chunk.chroma_id].updated_at = now

    expected_ids = {c.chroma_id for c in chunks}
    stale_ids = [cid for cid in registry if cid not in expected_ids]
    if stale_ids:
        collection.delete(ids=stale_ids)
        for cid in stale_ids:
            db.delete(registry[cid])

    return SyncCounts(
        chunks_total=len(chunks),
        embedded=len(to_embed),
        unchanged=unchanged,
        removed=len(stale_ids),
    )


def build_index(
    db: Session, embedder: EmbeddingProvider, chroma_dir: str | None = None
) -> dict:
    """Full rebuild across all properties and sources. Still incremental by
    hash, so re-running with no data change embeds nothing."""
    dev = DevelopmentDataProvider()
    chunks = build_chunks(db, content_provider=dev, review_provider=dev)
    scope_rows = db.query(RAGChunk).all()
    counts = apply_chunk_sync(db, embedder, chunks, scope_rows, chroma_dir)
    db.commit()

    summary = {
        "chunks_total": counts.chunks_total,
        "embedded": counts.embedded,
        "unchanged": counts.unchanged,
        "removed": counts.removed,
        "embedder": embedder.key,
        "ran_at": datetime.now(timezone.utc).isoformat(),
    }
    state_path = Path(chroma_dir or settings.chroma_dir) / STATE_FILENAME
    state_path.parent.mkdir(parents=True, exist_ok=True)
    state_path.write_text(json.dumps(summary))
    return summary
