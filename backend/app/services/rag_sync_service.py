"""Automatic RAG synchronization.

Imports do not embed inline. They enqueue a RagSyncJob describing what changed
(property + source), and a worker processes the queue: identify affected
chunks, recompute hashes, re-embed only what changed, update Chroma
incrementally, mark the job complete. The UI never waits on embeddings.

A full rebuild happens only when the embedding provider or version changes
(detected from the registry), never for an ordinary import.

Everything here is dependency-injected (db, embedding provider, chroma dir) so
tests are deterministic and never hit the network.
"""

from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.connectors.development import DevelopmentDataProvider
from app.db import SessionLocal
from app.models import RagSyncJob, RagSyncStatus, RAGChunk
from app.providers.base import EmbeddingProvider, MissingAPIKeyError
from app.providers.registry import get_embedding_provider
from app.services.rag.chunker import build_chunks
from app.services.rag.indexer import apply_chunk_sync


def enqueue_sync(
    db: Session,
    property_id: int | None = None,
    source: str | None = None,
    reason: str = "manual",
) -> RagSyncJob:
    """Record a pending sync. Fast: one row, no embedding work."""
    job = RagSyncJob(
        property_id=property_id,
        source=source,
        reason=reason,
        status=RagSyncStatus.QUEUED,
    )
    db.add(job)
    db.commit()
    db.refresh(job)
    return job


def _provider_changed(db: Session, provider: EmbeddingProvider) -> bool:
    """True if any indexed chunk was embedded by a different provider/version.
    Such a change invalidates the whole vector space and forces a full
    rebuild rather than a scoped update."""
    return (
        db.query(RAGChunk)
        .filter(
            (RAGChunk.provider != provider.name)
            | (RAGChunk.embedding_version != provider.version)
        )
        .first()
        is not None
    )


def process_job(
    db: Session,
    job: RagSyncJob,
    provider: EmbeddingProvider | None = None,
    chroma_dir: str | None = None,
) -> RagSyncJob:
    provider = provider or get_embedding_provider()
    job.status = RagSyncStatus.RUNNING
    job.started_at = datetime.now(timezone.utc)
    db.commit()

    try:
        dev = DevelopmentDataProvider()
        full = _provider_changed(db, provider) or (
            job.property_id is None and job.source is None
        )
        if full:
            chunks = build_chunks(db, content_provider=dev, review_provider=dev)
            scope_rows = db.query(RAGChunk).all()
        else:
            # Content, review, property-context, and traffic changes each feed a
            # derived intelligence chunk, so widen those jobs to refresh it too.
            # AI Query Signals derives from GA4 (AI referrals), GSC (search-
            # adjacent), and content, so those three widen it.
            # Every intelligence source also feeds the Opportunity Engine, which
            # unifies all module recommendations, so each widen list refreshes it.
            if job.source == "content":
                sources = ["content", "content_intelligence", "ai_query_signals"]
            elif job.source == "ga4":
                sources = ["ga4", "ai_query_signals"]
            elif job.source == "gsc":
                sources = ["gsc", "ai_query_signals"]
            elif job.source == "ai_visibility":
                # New AI Visibility data feeds competitor share-of-voice too.
                sources = ["ai_visibility", "competitor_intelligence"]
            elif job.source == "competitors":
                sources = ["competitor_intelligence"]
            elif job.source == "reviews":
                sources = ["reviews", "review_intelligence"]
            elif job.source == "property_context":
                # Derived analyses that reference property context (Content/Review
                # Intelligence, and the AI Visibility hallucination hook).
                sources = [
                    "property_context", "content_intelligence",
                    "review_intelligence", "ai_visibility",
                ]
            elif job.source:
                sources = [job.source]
            else:
                sources = None
            if sources is not None and job.source in (
                "content", "ga4", "gsc", "ai_visibility", "competitors",
                "reviews", "property_context",
            ):
                sources = sources + ["opportunity_engine"]
            chunks = build_chunks(
                db,
                property_id=job.property_id,
                sources=sources,
                content_provider=dev,
                review_provider=dev,
            )
            scope_q = db.query(RAGChunk)
            if job.property_id is not None:
                scope_q = scope_q.filter(RAGChunk.property_id == job.property_id)
            if sources is not None:
                scope_q = scope_q.filter(RAGChunk.source.in_(sources))
            scope_rows = scope_q.all()

        counts = apply_chunk_sync(db, provider, chunks, scope_rows, chroma_dir)
        job.chunks_total = counts.chunks_total
        job.chunks_embedded = counts.embedded
        job.chunks_unchanged = counts.unchanged
        job.chunks_removed = counts.removed
        job.status = RagSyncStatus.COMPLETED
        job.completed_at = datetime.now(timezone.utc)
        db.commit()
    except Exception as exc:
        db.rollback()
        job.status = RagSyncStatus.FAILED
        job.error_message = str(exc)[:500]
        job.completed_at = datetime.now(timezone.utc)
        db.commit()
    return job


def drain_queue(
    db: Session | None = None,
    provider: EmbeddingProvider | None = None,
    chroma_dir: str | None = None,
    limit: int = 100,
) -> dict:
    """Process queued jobs. Opens its own session when none is injected (the
    background-task path); tests inject a session for determinism."""
    own = db is None
    if own:
        db = SessionLocal()
    try:
        jobs = (
            db.query(RagSyncJob)
            .filter(RagSyncJob.status == RagSyncStatus.QUEUED)
            .order_by(RagSyncJob.id)
            .limit(limit)
            .all()
        )
        if not jobs:
            return {"processed": 0, "failed": 0}

        try:
            provider = provider or get_embedding_provider()
        except MissingAPIKeyError as exc:
            # No provider available: fail the jobs readably rather than crash.
            for job in jobs:
                job.status = RagSyncStatus.FAILED
                job.error_message = str(exc)[:500]
                job.completed_at = datetime.now(timezone.utc)
            db.commit()
            return {"processed": 0, "failed": len(jobs)}

        failed = 0
        for job in jobs:
            process_job(db, job, provider, chroma_dir)
            if job.status == RagSyncStatus.FAILED:
                failed += 1
        return {"processed": len(jobs) - failed, "failed": failed}
    finally:
        if own:
            db.close()
