# Import every model module so Base.metadata sees all tables (Alembic autogenerate
# and create_all both depend on this).
from app.models.company import Company
from app.models.property import Property
from app.models.uploads import Upload, SourceType, UploadStatus
from app.models.traffic import (
    GA4SessionsDaily,
    GSCPerformanceDaily,
    GBPMetricsDaily,
    PaidMediaDaily,
)
from app.models.crm import CRMLead, LeadStatus
from app.models.connections import (
    DataConnection,
    OAuthStatus,
    SyncFrequency,
    SyncJob,
    SyncJobStatus,
    SyncStatus,
)
from app.models.rag import RAGChunk
from app.models.rag_sync import RagSyncJob, RagSyncStatus
from app.models.content import PropertyContent, CANONICAL_PAGES
from app.models.property_profile import PropertyProfile
from app.models.reviews import PropertyReview
from app.models.nora import NoraConversation, NoraMessage, MessageRole
from app.models.reports import Report, ReportType
from app.models.ai_visibility import AIVisibilityQuery
from app.models.ai_visibility_schedule import (
    AIVisibilityPrompt,
    AIVisibilityScoreHistory,
)
from app.models.competitor import Competitor

__all__ = [
    "Company",
    "Property",
    "Upload",
    "SourceType",
    "UploadStatus",
    "GA4SessionsDaily",
    "GSCPerformanceDaily",
    "GBPMetricsDaily",
    "PaidMediaDaily",
    "CRMLead",
    "LeadStatus",
    "DataConnection",
    "SyncJob",
    "OAuthStatus",
    "SyncFrequency",
    "SyncStatus",
    "SyncJobStatus",
    "RAGChunk",
    "RagSyncJob",
    "RagSyncStatus",
    "PropertyContent",
    "CANONICAL_PAGES",
    "PropertyProfile",
    "PropertyReview",
    "NoraConversation",
    "NoraMessage",
    "MessageRole",
    "Report",
    "ReportType",
    "AIVisibilityQuery",
    "AIVisibilityPrompt",
    "AIVisibilityScoreHistory",
    "Competitor",
]
