"""Cache of pages AI answers cite, for "mentioned on page" (Phase 19)

New table ai_cited_pages (plain create_table).

Revision ID: c8d9e0f1a2b3
Revises: b7c8d9e0f1a2
Create Date: 2026-09-16

"""

import sqlalchemy as sa
from alembic import op

revision = "c8d9e0f1a2b3"
down_revision = "b7c8d9e0f1a2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ai_cited_pages",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("normalized_url", sa.String(1000), nullable=False),
        sa.Column("url", sa.String(2000), nullable=False),
        sa.Column("domain", sa.String(255), nullable=False),
        sa.Column("fetched_at", sa.DateTime(), nullable=False),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("http_status", sa.Integer(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("title", sa.String(500), nullable=True),
        sa.Column("body", sa.Text(), nullable=True),
        sa.Column("char_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("source", sa.String(20), nullable=False, server_default="fetch"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_index("uq_ai_cited_pages_url", "ai_cited_pages", ["normalized_url"], unique=True)
    op.create_index("ix_ai_cited_pages_fetched", "ai_cited_pages", ["fetched_at"])


def downgrade() -> None:
    op.drop_table("ai_cited_pages")
