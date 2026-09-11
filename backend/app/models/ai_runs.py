"""AI run records (Phase 19 Observatory).

One row per attempt to execute a prompt against an AI platform: the cost and
outcome ledger. The verbatim answer lives in AIVisibilityQuery (the evidence
record, which only ever holds successful responses); this table also keeps
failed and discarded attempts because they spent real money and must count
against budgets. property_id is nullable so market-scoped runs (one shared
observation scored against many properties, Phase 3) fit without a second
table. organization_id / market_id are plain integers here until the
Organization and Market tables land (Phase 1b), when the FKs are added.
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

RUN_RUNNING = "running"
RUN_SUCCESS = "success"
RUN_FAILED = "failed"
RUN_DISCARDED = "discarded"

SCOPE_PROPERTY = "property"
SCOPE_MARKET = "market"
SCOPE_FEATURE = "feature"
SCOPE_BRAND = "brand"
SCOPE_SENTINEL = "sentinel"


class AIRun(Base):
    __tablename__ = "ai_runs"
    __table_args__ = (
        Index("ix_ai_runs_property_started", "property_id", "started_at"),
        Index("ix_ai_runs_prompt_started", "prompt_id", "started_at"),
        Index("ix_ai_runs_market_started", "market_id", "started_at"),
        Index("ix_ai_runs_org_started", "organization_id", "started_at"),
        Index("ix_ai_runs_status", "status", "id"),
        Index("ix_ai_runs_provider_started", "provider", "started_at"),
        Index("ix_ai_runs_response_hash", "response_hash"),
        Index("ix_ai_runs_repeat_group", "repeat_group_key"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    organization_id: Mapped[int | None] = mapped_column(Integer)
    prompt_id: Mapped[int | None] = mapped_column(ForeignKey("ai_visibility_prompts.id"))
    cluster_id: Mapped[int | None] = mapped_column(Integer)
    market_id: Mapped[int | None] = mapped_column(Integer)
    property_id: Mapped[int | None] = mapped_column(ForeignKey("properties.id"))
    run_scope: Mapped[str] = mapped_column(String(20), default=SCOPE_PROPERTY)
    platform: Mapped[str] = mapped_column(String(50))
    provider: Mapped[str] = mapped_column(String(30))
    model_requested: Mapped[str | None] = mapped_column(String(100))
    # Model as reported back by the provider; may differ from requested.
    model: Mapped[str | None] = mapped_column(String(100))
    repeat_index: Mapped[int] = mapped_column(Integer, default=0)
    repeat_group_key: Mapped[str | None] = mapped_column(String(160))
    job_id: Mapped[int | None] = mapped_column(Integer)
    status: Mapped[str] = mapped_column(String(20), default=RUN_RUNNING)
    error_class: Mapped[str | None] = mapped_column(String(100))
    error_message: Mapped[str | None] = mapped_column(Text)
    retry_count: Mapped[int] = mapped_column(Integer, default=0)
    started_at: Mapped[datetime] = mapped_column(DateTime)
    completed_at: Mapped[datetime | None] = mapped_column(DateTime)
    latency_ms: Mapped[int | None] = mapped_column(Integer)
    # None when the provider cannot say whether it browsed.
    browsed: Mapped[bool | None] = mapped_column(Boolean)
    # Token counts as reported by the provider; None = not reported.
    token_input: Mapped[int | None] = mapped_column(Integer)
    token_output: Mapped[int | None] = mapped_column(Integer)
    token_reasoning: Mapped[int | None] = mapped_column(Integer)
    token_cached: Mapped[int | None] = mapped_column(Integer)
    search_operations: Mapped[int] = mapped_column(Integer, default=0)
    # MODELED from reference pricing; None = UNAVAILABLE (no rate for model).
    estimated_cost: Mapped[float | None] = mapped_column(Float)
    pricing_version: Mapped[str | None] = mapped_column(String(40))
    response_hash: Mapped[str | None] = mapped_column(String(64))
    duplicate_of_run_id: Mapped[int | None] = mapped_column(Integer)
    provider_response_id: Mapped[str | None] = mapped_column(String(120))
    location: Mapped[dict | None] = mapped_column(JSON)
    created_at: Mapped[datetime] = mapped_column(DateTime, server_default=func.now())
