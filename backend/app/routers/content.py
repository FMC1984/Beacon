"""Website content management. Content is entered manually or pulled live via
POST /{property_id}/{page}/fetch (a plain HTTP fetch + text extraction, no
external AI - see app/services/content_fetch.py for what it can and can't do).
Saving a page enqueues a RAG sync so the knowledge base and Content
Intelligence chunks refresh in the background."""

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.orm import Session

from app.db import get_db
from app.extensions.hooks import trigger_rag_sync
from app.models import CANONICAL_PAGES, Property, PropertyContent
from app.schemas.content import (
    ContentFetchIn,
    ContentFetchOut,
    ContentPageIn,
    ContentPageOut,
)
from app.services.content_fetch import ContentFetchError, fetch_page_content

router = APIRouter(prefix="/content", tags=["content"])


def _require_property(db: Session, property_id: int) -> None:
    if db.get(Property, property_id) is None:
        raise HTTPException(status_code=404, detail="Property not found.")


def _require_canonical_page(page: str) -> str:
    page = page.strip().lower()
    if page not in CANONICAL_PAGES:
        raise HTTPException(
            status_code=422,
            detail="page must be one of: " + ", ".join(CANONICAL_PAGES),
        )
    return page


def _save_page(
    db: Session,
    property_id: int,
    page: str,
    title: str,
    body: str,
    mapped_keyword: str | None,
    source_url: str | None,
    updated_at: datetime | None = None,
) -> PropertyContent:
    row = (
        db.query(PropertyContent)
        .filter_by(property_id=property_id, page=page)
        .one_or_none()
    )
    if row is None:
        row = PropertyContent(property_id=property_id, page=page)
        db.add(row)
    row.title = title
    row.body = body
    row.mapped_keyword = mapped_keyword
    row.source_url = source_url
    row.updated_at = updated_at or datetime.now(timezone.utc)
    db.commit()
    db.refresh(row)
    trigger_rag_sync(db, property_id=property_id, source="content", reason="content_edit")
    return row


@router.get("/{property_id}", response_model=list[ContentPageOut])
def list_content(property_id: int, db: Session = Depends(get_db)):
    _require_property(db, property_id)
    return (
        db.query(PropertyContent)
        .filter_by(property_id=property_id)
        .order_by(PropertyContent.page)
        .all()
    )


@router.put("/{property_id}", response_model=ContentPageOut, status_code=200)
def upsert_content(
    property_id: int, payload: ContentPageIn, db: Session = Depends(get_db)
):
    _require_property(db, property_id)
    page = _require_canonical_page(payload.page)
    return _save_page(
        db,
        property_id,
        page,
        payload.title,
        payload.body,
        payload.mapped_keyword,
        payload.source_url,
        payload.updated_at,
    )


@router.post("/{property_id}/{page}/fetch", response_model=ContentFetchOut, status_code=200)
def fetch_content(
    property_id: int, page: str, payload: ContentFetchIn, db: Session = Depends(get_db)
):
    """Fetch `payload.url` live and save its extracted text as this page's
    content. Real text only, never fabricated; a suspiciously short result
    (e.g. a JS-rendered page) is surfaced via char_count, not hidden."""
    _require_property(db, property_id)
    page = _require_canonical_page(page)

    try:
        fetched = fetch_page_content(payload.url)
    except ContentFetchError as exc:
        raise HTTPException(status_code=422, detail=str(exc))

    if not fetched["body"]:
        raise HTTPException(
            status_code=422,
            detail=(
                f"Fetched {payload.url} but found no readable text. The page "
                "may be rendered by JavaScript, which this fetch cannot run."
            ),
        )

    row = _save_page(
        db,
        property_id,
        page,
        fetched["title"] or page.replace("_", " ").title(),
        fetched["body"],
        payload.mapped_keyword,
        payload.url,
    )
    return ContentFetchOut(
        page=row, char_count=fetched["char_count"], truncated=fetched["truncated"]
    )
