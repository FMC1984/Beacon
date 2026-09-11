"""Durable jobs, app state, monthly AI budgets (Phase 19, slice 1b)

Three new tables, plain create_table; no existing table changes.

Revision ID: c2d3e4f5a6b8
Revises: b1c2d3e4f5a7
Create Date: 2026-09-11

"""

import sqlalchemy as sa
from alembic import op

revision = "c2d3e4f5a6b8"
down_revision = "b1c2d3e4f5a7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "jobs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("job_type", sa.String(60), nullable=False),
        sa.Column("idempotency_key", sa.String(255), nullable=False, unique=True),
        sa.Column("payload", sa.JSON(), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="queued"),
        sa.Column("priority", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("run_after", sa.DateTime(), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("max_attempts", sa.Integer(), nullable=False, server_default="5"),
        sa.Column("lease_owner", sa.String(100), nullable=True),
        sa.Column("lease_expires_at", sa.DateTime(), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("error_class", sa.String(100), nullable=True),
        sa.Column("result", sa.JSON(), nullable=True),
        sa.Column("organization_id", sa.Integer(), nullable=True),
        sa.Column("market_id", sa.Integer(), nullable=True),
        sa.Column("property_id", sa.Integer(), nullable=True),
        sa.Column("parent_job_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_jobs_status_run_after_priority", "jobs", ["status", "run_after", "priority"])
    op.create_index("ix_jobs_type_status", "jobs", ["job_type", "status"])
    op.create_index("ix_jobs_org_created", "jobs", ["organization_id", "created_at"])
    op.create_index("ix_jobs_lease", "jobs", ["lease_owner"])

    op.create_table(
        "app_state",
        sa.Column("key", sa.String(100), primary_key=True),
        sa.Column("value", sa.JSON(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
    )

    op.create_table(
        "ai_budgets",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("scope_type", sa.String(20), nullable=False),
        sa.Column("scope_id", sa.Integer(), nullable=False),
        sa.Column("period", sa.String(7), nullable=False),
        sa.Column("allowance_runs", sa.Integer(), nullable=False),
        sa.Column("allowance_usd", sa.Float(), nullable=True),
        sa.Column("spent_runs", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("spent_usd", sa.Float(), nullable=False, server_default="0"),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_index(
        "uq_ai_budgets_scope_period", "ai_budgets", ["scope_type", "scope_id", "period"], unique=True
    )


def downgrade() -> None:
    op.drop_table("ai_budgets")
    op.drop_table("app_state")
    op.drop_table("jobs")
