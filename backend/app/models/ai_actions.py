"""Tracked actions (competitive roadmap 7: action lifecycle with retest).

An action a person chose to work on, from the Opportunity Engine, a truth
conflict or an area of concern: open, in progress, implemented, then
retested automatically against the evidence it came from. The row stores
what the action was about (`kind` + `target`), the baseline measured when it
was implemented, and every retest result, so the before and after are
auditable.
"""

from datetime import date, datetime

from sqlalchemy import JSON, Date, DateTime, ForeignKey, Index, Integer, String, Text, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base

KIND_LISTING = "listing_gap"   # a cited third-party page that does not name the property
KIND_CONTENT = "content_gap"   # an open content gap (cluster)
KIND_TOPIC = "topic"           # an area of concern (topic)
KIND_FACT = "fact"             # a fact AI answers get wrong
KIND_GENERAL = "general"       # anything else: no automatic retest
KINDS = (KIND_LISTING, KIND_CONTENT, KIND_TOPIC, KIND_FACT, KIND_GENERAL)

STATUS_OPEN = "open"
STATUS_IN_PROGRESS = "in_progress"
STATUS_IMPLEMENTED = "implemented"   # awaiting its retest
STATUS_RETESTED = "retested"         # outcome recorded
STATUS_DONE = "done"                 # general actions, closed by a person
STATUS_DISMISSED = "dismissed"
STATUSES = (STATUS_OPEN, STATUS_IN_PROGRESS, STATUS_IMPLEMENTED, STATUS_RETESTED, STATUS_DONE, STATUS_DISMISSED)

OUTCOME_RESOLVED = "resolved"          # the evidence the action was based on is gone
OUTCOME_PERSISTS = "persists"          # it is still there
OUTCOME_IMPROVED = "improved"          # topic visibility rose (association, not causation)
OUTCOME_NO_CHANGE = "no_change"
OUTCOME_DECLINED = "declined"
OUTCOME_INCONCLUSIVE = "inconclusive"  # not enough evidence after the retries


class AIAction(Base):
    __tablename__ = "ai_actions"
    __table_args__ = (
        Index("uq_ai_actions_key", "property_id", "action_key", unique=True),
        Index("ix_ai_actions_status_retest", "status", "retest_after"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organization_id: Mapped[int | None] = mapped_column(Integer)
    property_id: Mapped[int] = mapped_column(ForeignKey("properties.id"))
    action_key: Mapped[str] = mapped_column(String(64))
    kind: Mapped[str] = mapped_column(String(20))
    target: Mapped[dict | None] = mapped_column(JSON)
    source: Mapped[str | None] = mapped_column(String(40))
    source_label: Mapped[str | None] = mapped_column(String(60))
    title: Mapped[str] = mapped_column(String(300))
    reason: Mapped[str | None] = mapped_column(Text)
    evidence: Mapped[list | None] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(20), default=STATUS_OPEN)
    owner: Mapped[str | None] = mapped_column(String(120))
    notes: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime | None] = mapped_column(DateTime)
    implemented_on: Mapped[date | None] = mapped_column(Date)
    retest_after: Mapped[date | None] = mapped_column(Date)
    retest_count: Mapped[int] = mapped_column(Integer, default=0)
    retested_at: Mapped[datetime | None] = mapped_column(DateTime)
    baseline: Mapped[dict | None] = mapped_column(JSON)
    result: Mapped[dict | None] = mapped_column(JSON)
    outcome: Mapped[str | None] = mapped_column(String(20))
    content_change_id: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime | None] = mapped_column(DateTime)
