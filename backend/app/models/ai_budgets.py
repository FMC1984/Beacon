"""Monthly observation budgets (Phase 19, slice 1b).

One row per (scope, period): how many AI runs the scope is allowed this
month and how many it has spent. spent_runs counts every attempt (failed
and discarded runs cost money too); spent_usd sums estimated_cost where a
rate exists. Enforcement in the scheduler lands in Phase 5; from 1b the
ledger accrues so the numbers are real when it does.
"""

from datetime import datetime

from sqlalchemy import DateTime, Float, Index, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from app.db import Base

SCOPE_ORG = "org"
SCOPE_MARKET = "market"
SCOPE_PROPERTY = "property"


class AIBudget(Base):
    __tablename__ = "ai_budgets"
    __table_args__ = (
        Index("uq_ai_budgets_scope_period", "scope_type", "scope_id", "period", unique=True),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    scope_type: Mapped[str] = mapped_column(String(20))
    scope_id: Mapped[int] = mapped_column(Integer)
    period: Mapped[str] = mapped_column(String(7))  # YYYY-MM (UTC)
    allowance_runs: Mapped[int] = mapped_column(Integer)
    allowance_usd: Mapped[float | None] = mapped_column(Float)
    spent_runs: Mapped[int] = mapped_column(Integer, default=0)
    spent_usd: Mapped[float] = mapped_column(Float, default=0.0)
    updated_at: Mapped[datetime] = mapped_column(
        DateTime, server_default=func.now(), onupdate=func.now()
    )
