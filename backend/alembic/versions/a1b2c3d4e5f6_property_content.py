"""property content storage

Adds property_content for website pages the Content Intelligence engine reasons
over. Content flows into RAG via the Phase 9 ContentProvider seam.

Revision ID: a1b2c3d4e5f6
Revises: f2a9c1d34b57
Create Date: 2026-07-05

"""

import sqlalchemy as sa
from alembic import op

revision = "a1b2c3d4e5f6"
down_revision = "f2a9c1d34b57"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "property_content",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "property_id", sa.Integer(), sa.ForeignKey("properties.id"), nullable=False
        ),
        sa.Column("page", sa.String(50), nullable=False),
        sa.Column("title", sa.String(300), nullable=False),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("mapped_keyword", sa.String(300), nullable=True),
        sa.Column("source_url", sa.String(1000), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.UniqueConstraint("property_id", "page", name="uq_content_property_page"),
    )


def downgrade() -> None:
    op.drop_table("property_content")
