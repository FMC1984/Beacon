"""Phase 18A: new Share of Voice schema - models exist with the expected
shape and the migration is round-trippable (create_all matches what the
alembic chain produces, exercised indirectly via the shared db fixture)."""

from app.models import (
    AIShareOfVoiceSnapshot,
    AITopic,
    Competitor,
    Mention,
    Property,
)


def _prop(db, name="Schema Court"):
    p = Property(name=name, slug=name.lower().replace(" ", "-"), aliases=["Schema Ct"])
    db.add(p)
    db.commit()
    return p


def test_property_aliases_round_trip(db):
    p = _prop(db)
    db.refresh(p)
    assert p.aliases == ["Schema Ct"]


def test_ai_topic_unique_per_property(db):
    p = _prop(db)
    db.add(AITopic(property_id=p.id, topic_name="Amenities", priority="high"))
    db.commit()
    from sqlalchemy.exc import IntegrityError

    db.add(AITopic(property_id=p.id, topic_name="Amenities", priority="low"))
    try:
        db.commit()
        assert False, "expected a unique constraint violation"
    except IntegrityError:
        db.rollback()


def test_mention_row_shape(db):
    p = _prop(db)
    comp = Competitor(property_id=p.id, name="Rival Co")
    db.add(comp)
    db.commit()

    from app.models import AIVisibilityQuery
    from datetime import datetime, timezone

    q = AIVisibilityQuery(
        property_id=p.id, platform="chatgpt", prompt_text="q",
        raw_response_text="Schema Court beats Rival Co.",
        executed_at=datetime.now(timezone.utc),
    )
    db.add(q)
    db.commit()

    m = Mention(
        response_id=q.id, entity_type="property", entity_id=p.id,
        normalized_name=p.name, raw_matched_text="Schema Court",
        match_count=1, position=0, confidence=1.0,
    )
    db.add(m)
    db.commit()
    db.refresh(m)
    assert m.normalized_name == "Schema Court"
    assert m.raw_matched_text == "Schema Court"
    assert m.confidence == 1.0


def test_sov_snapshot_unique_per_scope_and_period(db):
    """The unique index applies where the scoping columns are non-null
    (standard SQL: NULL never equals NULL, so it can't itself deduplicate
    the all-topics/all-platforms "overall" row - snapshot_sov() handles that
    scope's idempotency procedurally with a delete-then-insert instead)."""
    from datetime import date
    from sqlalchemy.exc import IntegrityError

    p = _prop(db)
    topic = AITopic(property_id=p.id, topic_name="Amenities")
    db.add(topic)
    db.commit()

    row = AIShareOfVoiceSnapshot(
        property_id=p.id, topic_id=topic.id, platform="chatgpt",
        period_start=date(2026, 7, 1), period_end=date(2026, 7, 30),
        property_mentions=1, competitor_mentions=1, sample_size=2,
        sufficient=False, share_of_voice=None,
    )
    db.add(row)
    db.commit()

    dupe = AIShareOfVoiceSnapshot(
        property_id=p.id, topic_id=topic.id, platform="chatgpt",
        period_start=date(2026, 7, 1), period_end=date(2026, 7, 30),
        property_mentions=5, competitor_mentions=5, sample_size=10,
        sufficient=True, share_of_voice=0.5,
    )
    db.add(dupe)
    try:
        db.commit()
        assert False, "expected a unique constraint violation"
    except IntegrityError:
        db.rollback()


def test_ai_visibility_query_new_columns_default(db):
    from app.models import AIVisibilityQuery
    from datetime import datetime, timezone

    p = _prop(db)
    q = AIVisibilityQuery(
        property_id=p.id, platform="chatgpt", prompt_text="q",
        raw_response_text="text", executed_at=datetime.now(timezone.utc),
    )
    db.add(q)
    db.commit()
    db.refresh(q)
    assert q.execution_status == "success"
    assert q.property_mention_count == 0
    assert q.competitor_mention_count == 0
    assert q.model_metadata is None
