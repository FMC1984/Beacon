"""ga4 city and region

Adds optional visitor-geography columns to ga4_sessions_daily so the Audience
report can show where traffic comes from. Both are nullable: historical
uploads never carried a City/Region dimension, and GA4 emits "(not set)" when
it cannot resolve a location, so absence is the norm and must not read as zero.

Revision ID: c1a2d3e4f5b6
Revises: f3b1c2d4e5a6
Create Date: 2026-07-13

"""

import sqlalchemy as sa
from alembic import op

revision = "c1a2d3e4f5b6"
down_revision = "f3b1c2d4e5a6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("ga4_sessions_daily", sa.Column("city", sa.String(200), nullable=True))
    op.add_column("ga4_sessions_daily", sa.Column("region", sa.String(200), nullable=True))
    op.create_index(
        "ix_ga4_property_city", "ga4_sessions_daily", ["property_id", "city"]
    )


def downgrade() -> None:
    op.drop_index("ix_ga4_property_city", table_name="ga4_sessions_daily")
    op.drop_column("ga4_sessions_daily", "region")
    op.drop_column("ga4_sessions_daily", "city")
