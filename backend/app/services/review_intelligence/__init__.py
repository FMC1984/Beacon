"""Review Intelligence: a deterministic review-reasoning engine.

No external AI, no sentiment model, no embeddings for classification. Every
finding is fixed term/topic matching against normalized review text with fixed
scoring, so results are reproducible and explainable. Analysis is indexed as a
RAG chunk (plus one chunk per review) so Nora answers review questions with
citations, and every recommendation passes through the Phase 10.5 property-
context gating utility.
"""

from app.services.review_intelligence.analyzer import (
    analyze_property_reviews,
    review_intelligence_summary_text,
)

__all__ = ["analyze_property_reviews", "review_intelligence_summary_text"]
