"""Phase 19 (1b): content change detection. Unchanged pages hash the same
(no re-analysis), a changed body moves content_changed_at and re-tags
topics, and the diff names which topics moved."""

from datetime import datetime

from app.models import Property, PropertyContent
from app.services.observatory.content_change import (
    changed_topics,
    content_hash,
    normalize_text,
    refresh_content_hash,
)


def _prop(db, name="Hash Court"):
    p = Property(name=name, slug=name.lower().replace(" ", "-"))
    db.add(p)
    db.commit()
    return p


def test_normalization_ignores_whitespace_and_case():
    assert normalize_text("  Dogs   welcome\n\n at  the POOL ") == "dogs welcome at the pool"
    assert content_hash("Dogs welcome") == content_hash("  dogs   WELCOME ")
    assert content_hash("Dogs welcome") != content_hash("Cats welcome")


def test_first_hash_then_unchanged_then_changed(db):
    p = _prop(db)
    row = PropertyContent(
        property_id=p.id, page="amenities", title="Amenities",
        body="Resort-style pool and a dog park for your pets.",
    )
    db.add(row)
    db.commit()

    t1 = datetime(2026, 9, 1, 12, 0)
    assert refresh_content_hash(db, row, now=t1) is False  # first hash is not a "change"
    assert row.content_hash and row.hashed_at == t1 and row.content_changed_at is None
    assert "pets" in row.topics and "amenities" in row.topics

    t2 = datetime(2026, 9, 2, 12, 0)
    row.body = "Resort-style   POOL and a dog park for your pets."  # whitespace/case only
    assert refresh_content_hash(db, row, now=t2) is False
    assert row.content_changed_at is None and row.hashed_at == t2

    t3 = datetime(2026, 9, 3, 12, 0)
    old_topics = list(row.topics)
    row.body = "Resort-style pool. Covered parking and EV charging available."
    assert refresh_content_hash(db, row, now=t3) is True
    assert row.content_changed_at == t3
    diff = changed_topics(old_topics, row.topics)
    assert "pets" in diff["removed"]
    assert "parking" in diff["added"]


def test_content_api_stamps_hash_and_topics(client, db):
    p = _prop(db, "Api Hash Court")
    r = client.put(
        f"/api/content/{p.id}",
        json={"page": "faq", "title": "FAQ", "body": "Are dogs allowed? Yes, with a pet fee."},
    )
    assert r.status_code == 200, r.text
    row = db.query(PropertyContent).filter_by(property_id=p.id, page="faq").one()
    assert row.content_hash == content_hash("Are dogs allowed? Yes, with a pet fee.")
    assert "pets" in (row.topics or [])
    assert row.content_changed_at is None

    r = client.put(
        f"/api/content/{p.id}",
        json={"page": "faq", "title": "FAQ", "body": "Is parking included? Yes, one covered space."},
    )
    assert r.status_code == 200
    db.expire_all()
    row = db.query(PropertyContent).filter_by(property_id=p.id, page="faq").one()
    assert row.content_changed_at is not None
    assert "parking" in row.topics and "pets" not in row.topics
