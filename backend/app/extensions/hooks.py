"""Extension points for future intelligence modules.

These are seams only; nothing here is implemented as a product feature yet. The
point is that a future module (AI Visibility Scanner, Content Intelligence,
Competitor Intelligence, Review Intelligence, Opportunity Engine) can request a
RAG synchronization through a single, stable call without importing or changing
any existing service.

To add a module later: subclass IntelligenceModule, do its work, and call
self.request_reindex(...) when it changes data the knowledge base should learn.
No edits to the sync service, indexer, or Nora are required.
"""

from abc import ABC, abstractmethod

from sqlalchemy.orm import Session

from app.models import RagSyncJob
from app.services.rag_sync_service import enqueue_sync

# Named future modules. Registered here so the roadmap is discoverable in code;
# none are implemented (Phase 9 is architecture only).
FUTURE_MODULES = (
    "ai_visibility_scanner",
    "content_intelligence",
    "competitor_intelligence",
    "review_intelligence",
    "opportunity_engine",
)


def trigger_rag_sync(
    db: Session,
    property_id: int | None = None,
    source: str | None = None,
    reason: str = "manual",
) -> RagSyncJob:
    """The single seam any producer of data (uploads today, intelligence
    modules tomorrow) calls to keep the knowledge base current."""
    return enqueue_sync(db, property_id=property_id, source=source, reason=reason)


class IntelligenceModule(ABC):
    """Base class for future modules. Not implemented; defines the contract."""

    name: str = "unnamed_module"

    @abstractmethod
    def on_data_change(
        self, db: Session, property_id: int | None = None, source: str | None = None
    ) -> None:
        """Called when this module changes data the KB should reflect."""

    def request_reindex(
        self, db: Session, property_id: int | None = None, source: str | None = None
    ) -> RagSyncJob:
        return trigger_rag_sync(
            db, property_id=property_id, source=source, reason=f"module:{self.name}"
        )
