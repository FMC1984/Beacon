"""Tracked actions with retest (action lifecycle)

New table ai_actions (plain create_table).

Revision ID: 0a1b2c3d4e5f
Revises: f1a2b3c4d5e6
Create Date: 2026-09-18

"""

import sqlalchemy as sa
from alembic import op

revision = "0a1b2c3d4e5f"
down_revision = "f1a2b3c4d5e6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ai_actions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), nullable=True),
        sa.Column("property_id", sa.Integer(), sa.ForeignKey("properties.id"), nullable=False),
        sa.Column("action_key", sa.String(64), nullable=False),
        sa.Column("kind", sa.String(20), nullable=False),
        sa.Column("target", sa.JSON(), nullable=True),
        sa.Column("source", sa.String(40), nullable=True),
        sa.Column("source_label", sa.String(60), nullable=True),
        sa.Column("title", sa.String(300), nullable=False),
        sa.Column("reason", sa.Text(), nullable=True),
        sa.Column("evidence", sa.JSON(), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="open"),
        sa.Column("owner", sa.String(120), nullable=True),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("implemented_on", sa.Date(), nullable=True),
        sa.Column("retest_after", sa.Date(), nullable=True),
        sa.Column("retest_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("retested_at", sa.DateTime(), nullable=True),
        sa.Column("baseline", sa.JSON(), nullable=True),
        sa.Column("result", sa.JSON(), nullable=True),
        sa.Column("outcome", sa.String(20), nullable=True),
        sa.Column("content_change_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
    )
    op.create_index("uq_ai_actions_key", "ai_actions", ["property_id", "action_key"], unique=True)
    op.create_index("ix_ai_actions_status_retest", "ai_actions", ["status", "retest_after"])


def downgrade() -> None:
    op.drop_table("ai_actions")
