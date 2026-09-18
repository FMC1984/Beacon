"""AI readability checks (raw HTML, robots, structured data)

New table ai_readability_checks (plain create_table).

Revision ID: f1a2b3c4d5e6
Revises: e0f1a2b3c4d5
Create Date: 2026-09-17

"""

import sqlalchemy as sa
from alembic import op

revision = "f1a2b3c4d5e6"
down_revision = "e0f1a2b3c4d5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ai_readability_checks",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), nullable=True),
        sa.Column("property_id", sa.Integer(), sa.ForeignKey("properties.id"), nullable=False),
        sa.Column("checked_at", sa.DateTime(), nullable=False),
        sa.Column("site_url", sa.String(1000), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("pages", sa.JSON(), nullable=True),
        sa.Column("categories", sa.JSON(), nullable=True),
        sa.Column("robots", sa.JSON(), nullable=True),
        sa.Column("structured_data", sa.JSON(), nullable=True),
        sa.Column("findings", sa.JSON(), nullable=True),
        sa.Column("source", sa.String(20), nullable=False, server_default="fetch"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_index("ix_ai_readability_property_checked", "ai_readability_checks", ["property_id", "checked_at"])


def downgrade() -> None:
    op.drop_table("ai_readability_checks")
