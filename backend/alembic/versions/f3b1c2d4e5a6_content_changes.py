"""Content change log (Phase 16F)

Records operator-asserted website/optimization changes so the Content Impact
report can show performance around a change date. New table; a plain
create_table works in SQLite (batch mode is only needed to ALTER in a
constraint).

Revision ID: f3b1c2d4e5a6
Revises: e1f2a3b4c5d6
Create Date: 2026-07-12

"""

import sqlalchemy as sa
from alembic import op

revision = "f3b1c2d4e5a6"
down_revision = "e1f2a3b4c5d6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "content_changes",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("property_id", sa.Integer(), sa.ForeignKey("properties.id"), nullable=False),
        sa.Column("company_id", sa.Integer(), sa.ForeignKey("companies.id"), nullable=True),
        sa.Column("page_url", sa.String(1000), nullable=True),
        sa.Column("change_title", sa.String(300), nullable=False),
        sa.Column("change_type", sa.String(40), nullable=False),
        sa.Column("date_implemented", sa.Date(), nullable=False),
        sa.Column("notes", sa.Text(), nullable=True),
        sa.Column("related_opportunity", sa.String(500), nullable=True),
        sa.Column("created_by", sa.String(200), nullable=True),
        sa.Column("before_snapshot_ref", sa.String(500), nullable=True),
        sa.Column("after_snapshot_ref", sa.String(500), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_index(
        "ix_content_change_property_date",
        "content_changes",
        ["property_id", "date_implemented"],
    )


def downgrade() -> None:
    op.drop_index("ix_content_change_property_date", table_name="content_changes")
    op.drop_table("content_changes")
