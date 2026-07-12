"""ai_visibility_queries (Phase 11.5 AI Visibility Foundation)

Stores one row per executed external-AI query and its verbatim response. The
raw response is preserved permanently as the citation source. brand_mentioned
and sources_cited are deterministically parsed from the response text.

Revision ID: f6a7b8c9d0e1
Revises: e5f6a7b8c9d0
Create Date: 2026-07-05

"""

import sqlalchemy as sa
from alembic import op

revision = "f6a7b8c9d0e1"
down_revision = "e5f6a7b8c9d0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ai_visibility_queries",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "property_id", sa.Integer(), sa.ForeignKey("properties.id"), nullable=False
        ),
        sa.Column("platform", sa.String(50), nullable=False),
        sa.Column("prompt_text", sa.Text(), nullable=False),
        sa.Column("raw_response_text", sa.Text(), nullable=False),
        sa.Column("executed_at", sa.DateTime(), nullable=False),
        sa.Column(
            "brand_mentioned", sa.Boolean(), nullable=False, server_default=sa.false()
        ),
        sa.Column("sources_cited", sa.JSON(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
    )
    op.create_index(
        "ix_ai_visibility_property_executed",
        "ai_visibility_queries",
        ["property_id", "executed_at"],
    )
    op.create_index(
        "ix_ai_visibility_property_platform",
        "ai_visibility_queries",
        ["property_id", "platform"],
    )


def downgrade() -> None:
    op.drop_index("ix_ai_visibility_property_platform", "ai_visibility_queries")
    op.drop_index("ix_ai_visibility_property_executed", "ai_visibility_queries")
    op.drop_table("ai_visibility_queries")
