"""AI Visibility Foundation (Phase 11.5): the external-query layer.

Query execution against an external AI platform is the ONLY non-deterministic
step in Beacon. Everything downstream of the stored raw response - parsing,
mention detection, source extraction, the hallucination-check hook, the RAG
summary - is deterministic and explainable, following the Content/Review
Intelligence standard. This package builds the foundation only (provider seam,
storage, parsing, cost controls, hallucination hook, RAG chunk); the analysis /
scoring / recommendation module is Phase 12.
"""

from app.services.ai_visibility.analyzer import analyze_ai_visibility
from app.services.ai_visibility.chunk import ai_visibility_summary_text
from app.services.ai_visibility.execution import (
    RateLimitExceeded,
    budget_status,
    run_query,
)
from app.services.ai_visibility.hallucination import check_response_against_context
from app.services.ai_visibility.parsing import detect_mention, extract_sources

__all__ = [
    "analyze_ai_visibility",
    "ai_visibility_summary_text",
    "run_query",
    "budget_status",
    "RateLimitExceeded",
    "check_response_against_context",
    "detect_mention",
    "extract_sources",
]
