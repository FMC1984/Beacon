"""Internal status + maintenance endpoints. Single-user app, no auth by
design; these exist for debugging and demo prep, not for exposure."""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends
from sqlalchemy import func
from sqlalchemy.orm import Session

from app.config import settings
from app.constants import APP_PHASE, APP_VERSION, TEST_COUNT
from app.db import get_db
from app.models import NoraMessage, RAGChunk, RagSyncJob, RagSyncStatus
from app.providers.registry import embedding_provider_name, llm_provider_name
from app.services.rag.embedder import get_embedder
from app.services.rag.indexer import build_index, last_index_state
from app.services.rag.store import get_collection
from app.services.rag_sync_service import drain_queue

router = APIRouter(prefix="/admin", tags=["admin"])


def _openai_quota_check() -> str:
    if settings.demo_mode:
        return "skipped (demo mode)"
    if not settings.openai_api_key:
        return "skipped (no key)"
    try:
        from openai import OpenAI

        client = OpenAI(api_key=settings.openai_api_key, max_retries=0, timeout=10)
        client.embeddings.create(model="text-embedding-3-small", input="ping")
        return "ok"
    except Exception as exc:
        return f"failed: {str(exc)[:300]}"


def _chroma_status() -> dict:
    try:
        collection = get_collection()
        return {
            "status": "ok",
            "indexed_chunks": collection.count(),
            "embedder": collection.metadata.get("embedder"),
        }
    except Exception as exc:
        return {"status": f"failed: {str(exc)[:300]}", "indexed_chunks": None, "embedder": None}


@router.get("/status")
def status(db: Session = Depends(get_db)):
    last_message = (
        db.query(NoraMessage).order_by(NoraMessage.id.desc()).first()
    )
    return {
        "version": APP_VERSION,
        "phase": APP_PHASE,
        "test_count": TEST_COUNT,
        "demo_mode": settings.demo_mode,
        "openai_configured": bool(settings.openai_api_key),
        "openai_quota": _openai_quota_check(),
        "embedding_provider": embedding_provider_name(),
        "llm_provider": llm_provider_name(),
        "chroma": _chroma_status(),
        "registry_chunks": db.query(func.count(RAGChunk.id)).scalar(),
        "last_index_run": last_index_state(),
        "last_nora_message": (
            {
                "at": last_message.created_at.isoformat(),
                "role": last_message.role.value,
                "preview": last_message.content[:120],
            }
            if last_message
            else None
        ),
    }


@router.get("/sync-status")
def sync_status(db: Session = Depends(get_db)):
    """Knowledge Base synchronization status (Objective 6). Administrator view."""
    today_start = datetime.now(timezone.utc).replace(
        hour=0, minute=0, second=0, microsecond=0
    )
    last_completed = (
        db.query(func.max(RagSyncJob.completed_at))
        .filter(RagSyncJob.status == RagSyncStatus.COMPLETED)
        .scalar()
    )
    chroma = _chroma_status()
    recent = (
        db.query(RagSyncJob)
        .order_by(RagSyncJob.id.desc())
        .limit(10)
        .all()
    )
    last_rebuild = last_index_state()
    return {
        "last_sync": last_completed.isoformat() if last_completed else None,
        "chunks_indexed": chroma.get("indexed_chunks"),
        "chunks_updated_today": db.query(func.count(RAGChunk.id))
        .filter(RAGChunk.updated_at >= today_start)
        .scalar(),
        "queued_jobs": db.query(func.count(RagSyncJob.id))
        .filter(RagSyncJob.status == RagSyncStatus.QUEUED)
        .scalar(),
        "failed_jobs": db.query(func.count(RagSyncJob.id))
        .filter(RagSyncJob.status == RagSyncStatus.FAILED)
        .scalar(),
        "embedding_provider": embedding_provider_name(),
        "llm_provider": llm_provider_name(),
        "last_rebuild": last_rebuild["ran_at"] if last_rebuild else None,
        "recent_jobs": [
            {
                "id": j.id,
                "property_id": j.property_id,
                "source": j.source,
                "reason": j.reason,
                "status": j.status.value,
                "chunks_embedded": j.chunks_embedded,
                "chunks_total": j.chunks_total,
                "created_at": j.created_at.isoformat(),
                "error_message": j.error_message,
            }
            for j in recent
        ],
    }


@router.post("/process-queue")
def process_queue(db: Session = Depends(get_db)):
    """Drain queued RAG sync jobs now (the manual alternative to autosync / the
    standalone worker)."""
    result = drain_queue(db=db)
    return {"status": "ok", **result}


@router.post("/reindex")
def reindex(db: Session = Depends(get_db)):
    try:
        embedder = get_embedder()
        summary = build_index(db, embedder)
        return {"status": "ok", **summary}
    except Exception as exc:
        db.rollback()
        return {"status": "failed", "error": str(exc)[:500]}


@router.get("/retrieval-debug")
def retrieval_debug(
    q: str,
    property_id: int | None = None,
    source: str | None = None,
    top_k: int = 6,
    db: Session = Depends(get_db),
):
    """Developer-only view of hybrid retrieval (Phase 15b): why each chunk
    matched, component by component. Not surfaced in the end-user UI."""
    from app.services.rag.retriever import retrieve

    chunks = retrieve(
        db, get_embedder(), q, property_id=property_id, source=source, top_k=top_k
    )
    return {
        "query": q,
        "results": [
            {
                "chroma_id": c.chroma_id,
                "final_score": c.score,
                "components": c.match_explanation["components"],
                "weights": c.match_explanation["weights"],
                "matched_keywords": c.match_explanation["matched_keywords"],
                "matched_phrases": c.match_explanation["matched_phrases"],
                "matched_topics": c.match_explanation["matched_topics"],
                "matched_entities": c.match_explanation["matched_entities"],
                "citation": {
                    "source_table": c.citation.source_table,
                    "source_ref": c.citation.source_ref,
                    "date_range": c.citation.date_range,
                },
                "excerpt": c.text[:200],
            }
            for c in chunks
        ],
    }
