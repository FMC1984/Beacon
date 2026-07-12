"""property reviews (Review Intelligence)

Adds property_reviews. Partial unique index on (property_id, provider,
external_review_id) applies only when external_review_id IS NOT NULL, so
multiple manually entered (null-id) reviews coexist. Partial index works on
SQLite and Postgres.

Revision ID: c3d4e5f6a7b8
Revises: b2c3d4e5f6a7
Create Date: 2026-07-05

"""

import sqlalchemy as sa
from alembic import op

revision = "c3d4e5f6a7b8"
down_revision = "b2c3d4e5f6a7"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "property_reviews",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "property_id", sa.Integer(), sa.ForeignKey("properties.id"), nullable=False
        ),
        sa.Column("provider", sa.String(50), nullable=False),
        sa.Column("external_review_id", sa.String(200), nullable=True),
        sa.Column("author_name", sa.String(200), nullable=True),
        sa.Column("rating", sa.Float(), nullable=True),
        sa.Column("title", sa.String(500), nullable=True),
        sa.Column("body", sa.Text(), nullable=False),
        sa.Column("review_date", sa.Date(), nullable=True),
        sa.Column("response_text", sa.Text(), nullable=True),
        sa.Column("response_date", sa.Date(), nullable=True),
        sa.Column("source_url", sa.String(1000), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
    )
    op.create_index(
        "uq_review_external",
        "property_reviews",
        ["property_id", "provider", "external_review_id"],
        unique=True,
        sqlite_where=sa.text("external_review_id IS NOT NULL"),
        postgresql_where=sa.text("external_review_id IS NOT NULL"),
    )
    op.create_index(
        "ix_review_property_date", "property_reviews", ["property_id", "review_date"]
    )
    op.create_index(
        "ix_review_property_provider", "property_reviews", ["property_id", "provider"]
    )


def downgrade() -> None:
    op.drop_index("ix_review_property_provider", table_name="property_reviews")
    op.drop_index("ix_review_property_date", table_name="property_reviews")
    op.drop_index("uq_review_external", table_name="property_reviews")
    op.drop_table("property_reviews")
