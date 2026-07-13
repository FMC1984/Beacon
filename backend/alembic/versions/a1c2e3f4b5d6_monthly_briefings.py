"""Monthly Strategic Briefing snapshots (Phase 17A)

Frozen point-in-time briefing snapshots per property and calendar month.
New table; a plain create_table works in SQLite.

Revision ID: a1c2e3f4b5d6
Revises: e2f3a4b5c6d7
Create Date: 2026-07-13

"""

import sqlalchemy as sa
from alembic import op

revision = "a1c2e3f4b5d6"
down_revision = "e2f3a4b5c6d7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "monthly_briefings",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("property_id", sa.Integer(), sa.ForeignKey("properties.id"), nullable=False),
        sa.Column("period_start", sa.Date(), nullable=False),
        sa.Column("period_end", sa.Date(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("generated_by", sa.String(200), nullable=True),
        sa.Column("generated_at", sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_index(
        "ix_briefing_property_period",
        "monthly_briefings",
        ["property_id", "period_start"],
    )


def downgrade() -> None:
    op.drop_index("ix_briefing_property_period", table_name="monthly_briefings")
    op.drop_table("monthly_briefings")
