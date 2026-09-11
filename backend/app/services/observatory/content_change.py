"""Content change detection (Phase 19, slice 1b).

Beacon must not re-analyze unchanged website content. Every PropertyContent
row carries a sha256 of its normalized body; a refresh with the same hash
is a no-op, a different hash records content_changed_at and re-tags the
semantic topics so later phases can prioritize only the prompt clusters
whose topics actually moved (pets changed -> pet clusters, not everything).
"""

import hashlib
from datetime import datetime, timezone

from sqlalchemy.orm import Session

from app.models import PropertyContent
from app.services.semantic import enrich_text


def normalize_text(body: str | None) -> str:
    return " ".join((body or "").split()).lower()


def content_hash(body: str | None) -> str:
    return hashlib.sha256(normalize_text(body).encode("utf-8")).hexdigest()


def topics_for(body: str | None) -> list[str]:
    try:
        return sorted(enrich_text(body or "").get("topics") or [])
    except Exception:  # enrichment must never block a content save
        return []


def refresh_content_hash(db: Session, row: PropertyContent, now: datetime | None = None) -> bool:
    """Recompute the hash; True when the content changed since last time.
    First-time hashing counts as unchanged (there is no earlier state to
    compare with) but still tags topics. Does not commit."""
    now = now or datetime.now(timezone.utc).replace(tzinfo=None)
    digest = content_hash(row.body)
    previous = row.content_hash
    row.hashed_at = now
    if previous == digest:
        if row.topics is None:
            row.topics = topics_for(row.body)
        return False
    row.content_hash = digest
    row.topics = topics_for(row.body)
    if previous is not None:
        row.content_changed_at = now
    return previous is not None


def changed_topics(old: list[str] | None, new: list[str] | None) -> dict:
    before, after = set(old or []), set(new or [])
    return {
        "added": sorted(after - before),
        "removed": sorted(before - after),
        "kept": sorted(before & after),
    }
