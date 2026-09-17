"""Property fact provenance (Truth layer v1)

New table property_facts (plain create_table).

Revision ID: e0f1a2b3c4d5
Revises: d9e0f1a2b3c4
Create Date: 2026-09-17

"""

import sqlalchemy as sa
from alembic import op

revision = "e0f1a2b3c4d5"
down_revision = "d9e0f1a2b3c4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "property_facts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), nullable=True),
        sa.Column("property_id", sa.Integer(), sa.ForeignKey("properties.id"), nullable=False),
        sa.Column("fact_key", sa.String(80), nullable=False),
        sa.Column("source_of_truth", sa.String(200), nullable=True),
        sa.Column("verified_at", sa.DateTime(), nullable=True),
        sa.Column("verified_by", sa.String(120), nullable=True),
        sa.Column("effective_date", sa.Date(), nullable=True),
        sa.Column("freshness", sa.String(20), nullable=False, server_default="stable"),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
    )
    op.create_index("uq_property_facts_key", "property_facts", ["property_id", "fact_key"], unique=True)


def downgrade() -> None:
    op.drop_table("property_facts")
