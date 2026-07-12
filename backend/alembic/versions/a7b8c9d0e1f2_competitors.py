"""competitors (Phase 13 Competitor Intelligence)

Operator-asserted competitor set per property. Used to compute AI-answer share
of voice deterministically over stored AI Visibility responses.

Revision ID: a7b8c9d0e1f2
Revises: f6a7b8c9d0e1
Create Date: 2026-07-06

"""

import sqlalchemy as sa
from alembic import op

revision = "a7b8c9d0e1f2"
down_revision = "f6a7b8c9d0e1"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "competitors",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "property_id", sa.Integer(), sa.ForeignKey("properties.id"), nullable=False
        ),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("aliases", sa.JSON(), nullable=True),
        sa.Column("domain", sa.String(1000), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False
        ),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
    )
    op.create_index(
        "uq_competitor_name", "competitors", ["property_id", "name"], unique=True
    )
    op.create_index("ix_competitor_property", "competitors", ["property_id"])


def downgrade() -> None:
    op.drop_index("ix_competitor_property", "competitors")
    op.drop_index("uq_competitor_name", "competitors")
    op.drop_table("competitors")
