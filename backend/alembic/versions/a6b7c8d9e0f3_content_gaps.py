"""AI content gaps (Phase 19, slice 6)

New table ai_content_gaps (plain create_table).

Revision ID: a6b7c8d9e0f3
Revises: f5a6b7c8d9e1
Create Date: 2026-09-12

"""

import sqlalchemy as sa
from alembic import op

revision = "a6b7c8d9e0f3"
down_revision = "f5a6b7c8d9e1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ai_content_gaps",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), nullable=True),
        sa.Column("property_id", sa.Integer(), sa.ForeignKey("properties.id"), nullable=False),
        sa.Column("cluster_id", sa.Integer(), nullable=False),
        sa.Column("topic_key", sa.String(60), nullable=True),
        sa.Column("question", sa.Text(), nullable=False),
        sa.Column("gap_key", sa.String(100), nullable=False),
        sa.Column("target_page", sa.String(50), nullable=True),
        sa.Column("page_exists", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("missing_terms", sa.JSON(), nullable=True),
        sa.Column("covered_terms", sa.JSON(), nullable=True),
        sa.Column("evidence", sa.JSON(), nullable=True),
        sa.Column("visibility", sa.Float(), nullable=True),
        sa.Column("competitor_presence", sa.Float(), nullable=True),
        sa.Column("title", sa.String(300), nullable=False),
        sa.Column("recommendation", sa.Text(), nullable=False),
        sa.Column("state", sa.String(30), nullable=False),
        sa.Column("gate_reason", sa.Text(), nullable=True),
        sa.Column("impact", sa.String(10), nullable=False, server_default="Medium"),
        sa.Column("effort", sa.String(10), nullable=False, server_default="Medium"),
        sa.Column("status", sa.String(20), nullable=False, server_default="open"),
        sa.Column("first_detected", sa.DateTime(), nullable=False),
        sa.Column("last_evaluated", sa.DateTime(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_index("uq_ai_content_gaps_key", "ai_content_gaps", ["gap_key"], unique=True)
    op.create_index("ix_ai_content_gaps_property_status", "ai_content_gaps", ["property_id", "status"])


def downgrade() -> None:
    op.drop_table("ai_content_gaps")
