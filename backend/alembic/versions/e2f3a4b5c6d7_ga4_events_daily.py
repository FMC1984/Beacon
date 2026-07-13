"""ga4 events daily

Adds ga4_events_daily: GA4 event counts by event name and day (page_view,
scroll, click, ...). Beacon previously collapsed event-level exports into
session counts and discarded event names; this table stores them so the
Dashboard and SEO report can show the event breakdown.

Revision ID: e2f3a4b5c6d7
Revises: c1a2d3e4f5b6
Create Date: 2026-07-13

"""

import sqlalchemy as sa
from alembic import op

revision = "e2f3a4b5c6d7"
down_revision = "c1a2d3e4f5b6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ga4_events_daily",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("property_id", sa.Integer(), sa.ForeignKey("properties.id"), nullable=False),
        sa.Column("upload_id", sa.Integer(), sa.ForeignKey("uploads.id"), nullable=True),
        sa.Column("sync_job_id", sa.Integer(), sa.ForeignKey("sync_jobs.id"), nullable=True),
        sa.Column("source_line", sa.Integer(), nullable=True),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("event_name", sa.String(200), nullable=False),
        sa.Column("event_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_users", sa.Integer(), nullable=False, server_default="0"),
        sa.CheckConstraint(
            "upload_id IS NOT NULL OR sync_job_id IS NOT NULL",
            name="ck_ga4_events_daily_provenance",
        ),
    )
    op.create_index("ix_ga4_events_property_date", "ga4_events_daily", ["property_id", "date"])
    op.create_index("ix_ga4_events_name", "ga4_events_daily", ["property_id", "event_name"])


def downgrade() -> None:
    op.drop_index("ix_ga4_events_name", table_name="ga4_events_daily")
    op.drop_index("ix_ga4_events_property_date", table_name="ga4_events_daily")
    op.drop_table("ga4_events_daily")
