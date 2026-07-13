"""Briefing share tokens (Phase 17D)

A frozen briefing snapshot can be shared via an unguessable token on a public,
key-exempt route. Nullable column + unique index; plain add_column (no FK, so
no batch mode needed).

Revision ID: b2d3f4a5c6e7
Revises: a1c2e3f4b5d6
Create Date: 2026-07-13

"""

import sqlalchemy as sa
from alembic import op

revision = "b2d3f4a5c6e7"
down_revision = "a1c2e3f4b5d6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "monthly_briefings",
        sa.Column("share_token", sa.String(64), nullable=True),
    )
    op.create_index(
        "uq_briefing_share_token", "monthly_briefings", ["share_token"], unique=True
    )


def downgrade() -> None:
    op.drop_index("uq_briefing_share_token", table_name="monthly_briefings")
    op.drop_column("monthly_briefings", "share_token")
