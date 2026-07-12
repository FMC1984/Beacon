"""Content Intelligence: a deterministic content-reasoning engine.

No external AI is called for analysis. Everything is term/topic matching against
the property's ingested content, with fixed thresholds, so results are
reproducible and every score is explainable. The engine reads content through
the Phase 9 ContentProvider and its findings are indexed as RAG chunks so Nora
can answer content questions with citations.
"""

from app.services.content_intelligence.analyzer import (
    analyze_property,
    content_intelligence_summary_text,
)

__all__ = ["analyze_property", "content_intelligence_summary_text"]
