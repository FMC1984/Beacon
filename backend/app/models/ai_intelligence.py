"""Observatory intelligence tables (Phase 19, slice 5).

- AIEntityDecision: an operator's confirm/ignore decision on an AI-discovered
  name, per property. Competitors stay operator-named (see Competitor): a
  discovered name becomes a Competitor row only through a confirm decision.
- AIClaim: a factual claim an AI answer made about a property, with a
  verification status that is never "false" without reliable evidence.
- AIVisibilityAlert: a deduplicated, evidence-carrying change worth a look.
- AIRunSchedule / AIScheduleDecision: the adaptive scheduler's plan rows and
  the log of every planning decision (why a run was or was not enqueued).
"""

from datetime import datetime

from sqlalchemy import (
    JSON,
    Boolean,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base

DECISION_CONFIRMED = "confirmed"
DECISION_IGNORED = "ignored"

CLAIM_CONFIRMED = "confirmed"
CLAIM_LIKELY_ACCURATE = "likely_accurate"
CLAIM_CONFLICT = "conflict_detected"
CLAIM_UNVERIFIABLE = "unable_to_verify"
CLAIM_STATUSES = (CLAIM_CONFIRMED, CLAIM_LIKELY_ACCURATE, CLAIM_CONFLICT, CLAIM_UNVERIFIABLE)

ALERT_OPEN = "open"
ALERT_ACKNOWLEDGED = "acknowledged"
ALERT_RESOLVED = "resolved"


class AIEntityDecision(Base):
    __tablename__ = "ai_entity_decisions"
    __table_args__ = (
        Index("uq_ai_entity_decisions_entity_property", "entity_id", "property_id", unique=True),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    entity_id: Mapped[int] = mapped_column(ForeignKey("ai_discovered_entities.id"))
    property_id: Mapped[int] = mapped_column(ForeignKey("properties.id"))
    decision: Mapped[str] = mapped_column(String(20))
    competitor_id: Mapped[int | None] = mapped_column(Integer)
    decided_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())


class AIClaim(Base):
    __tablename__ = "ai_claims"
    __table_args__ = (
        Index("uq_ai_claims_property_hash", "property_id", "claim_hash", unique=True),
        Index("ix_ai_claims_property_status", "property_id", "verification_status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organization_id: Mapped[int | None] = mapped_column(Integer)
    property_id: Mapped[int] = mapped_column(ForeignKey("properties.id"))
    claim_type: Mapped[str] = mapped_column(String(40))
    claim_topic: Mapped[str | None] = mapped_column(String(60))
    claim_value: Mapped[str] = mapped_column(String(200))
    claim_text: Mapped[str] = mapped_column(Text)
    verification_status: Mapped[str] = mapped_column(String(30))
    verification_method: Mapped[str] = mapped_column(String(60))
    evidence: Mapped[str] = mapped_column(Text)
    known_value: Mapped[str | None] = mapped_column(String(200))
    severity: Mapped[str] = mapped_column(String(10), default="low")
    claim_hash: Mapped[str] = mapped_column(String(64))
    first_seen: Mapped[datetime] = mapped_column(DateTime)
    last_seen: Mapped[datetime] = mapped_column(DateTime)
    occurrence_count: Mapped[int] = mapped_column(Integer, default=1)
    response_ids: Mapped[list | None] = mapped_column(JSON)
    platforms: Mapped[list | None] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(20), default="open")
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime | None] = mapped_column(DateTime)


class AIVisibilityAlert(Base):
    __tablename__ = "ai_visibility_alerts"
    __table_args__ = (
        Index("uq_ai_visibility_alerts_dedupe", "dedupe_key", unique=True),
        Index("ix_ai_visibility_alerts_property_status", "property_id", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organization_id: Mapped[int | None] = mapped_column(Integer)
    property_id: Mapped[int | None] = mapped_column(Integer)
    market_id: Mapped[int | None] = mapped_column(Integer)
    alert_type: Mapped[str] = mapped_column(String(40))
    severity: Mapped[str] = mapped_column(String(10))
    title: Mapped[str] = mapped_column(String(300))
    detail: Mapped[str] = mapped_column(Text)
    evidence: Mapped[dict | None] = mapped_column(JSON)
    metric_before: Mapped[float | None] = mapped_column(Float)
    metric_after: Mapped[float | None] = mapped_column(Float)
    data_label: Mapped[str] = mapped_column(String(20), default="MEASURED")
    status: Mapped[str] = mapped_column(String(20), default=ALERT_OPEN)
    dedupe_key: Mapped[str] = mapped_column(String(200))
    escalated: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime | None] = mapped_column(DateTime)


class AIRunSchedule(Base):
    __tablename__ = "ai_run_schedule"
    __table_args__ = (
        Index("uq_ai_run_schedule_key", "schedule_key", unique=True),
        Index("ix_ai_run_schedule_next", "status", "next_run_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organization_id: Mapped[int | None] = mapped_column(Integer)
    prompt_id: Mapped[int] = mapped_column(ForeignKey("ai_visibility_prompts.id"))
    cluster_id: Mapped[int | None] = mapped_column(Integer)
    property_id: Mapped[int | None] = mapped_column(Integer)
    market_id: Mapped[int | None] = mapped_column(Integer)
    platform: Mapped[str] = mapped_column(String(50))
    tier: Mapped[str] = mapped_column(String(30))
    tier_override: Mapped[str | None] = mapped_column(String(30))
    escalation_until: Mapped[datetime | None] = mapped_column(DateTime)
    cadence_days: Mapped[int] = mapped_column(Integer)
    repeat_count: Mapped[int] = mapped_column(Integer, default=1)
    next_run_at: Mapped[datetime | None] = mapped_column(DateTime)
    last_run_at: Mapped[datetime | None] = mapped_column(DateTime)
    last_priority_score: Mapped[float | None] = mapped_column(Float)
    priority_components: Mapped[dict | None] = mapped_column(JSON)
    status: Mapped[str] = mapped_column(String(20), default="active")
    schedule_key: Mapped[str] = mapped_column(String(200))
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
    updated_at: Mapped[datetime | None] = mapped_column(DateTime)


class AIScheduleDecision(Base):
    __tablename__ = "ai_schedule_decisions"
    __table_args__ = (Index("ix_ai_schedule_decisions_plan", "plan_key", "id"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    plan_key: Mapped[str] = mapped_column(String(100))
    schedule_id: Mapped[int | None] = mapped_column(Integer)
    prompt_id: Mapped[int | None] = mapped_column(Integer)
    decision: Mapped[str] = mapped_column(String(30))  # enqueued | skipped_budget | not_due | dry_run
    reason: Mapped[str] = mapped_column(Text)
    priority_score: Mapped[float | None] = mapped_column(Float)
    priority_components: Mapped[dict | None] = mapped_column(JSON)
    job_ids: Mapped[list | None] = mapped_column(JSON)
    dry_run: Mapped[bool] = mapped_column(Boolean, default=False)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
