"""Persist provider-observed retrieval queries (Phase 19). OBSERVED provider
behavior for one API call; never consumer search volume."""

from sqlalchemy.orm import Session

from app.models import AIRun, AISearchQuery, AIVisibilityQuery


def persist_search_queries(
    db: Session,
    response: AIVisibilityQuery,
    run: AIRun | None,
    queries: list[str] | tuple[str, ...],
    captured_from: str,
) -> list[AISearchQuery]:
    """Idempotent: replaces the response's retrieval-query rows. Blank and
    duplicate queries are dropped, order preserved."""
    db.query(AISearchQuery).filter_by(response_id=response.id).delete()
    rows: list[AISearchQuery] = []
    seen: set[str] = set()
    for q in queries:
        text = (q or "").strip()
        if not text or text.lower() in seen:
            continue
        seen.add(text.lower())
        row = AISearchQuery(
            response_id=response.id,
            run_id=run.id if run else None,
            provider=(run.provider if run else None) or "unknown",
            query_text=text,
            query_order=len(rows),
            captured_from=captured_from,
        )
        db.add(row)
        rows.append(row)
    return rows
