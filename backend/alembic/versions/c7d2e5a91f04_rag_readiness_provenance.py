"""rag readiness provenance

Citation-grade provenance so Phase 7 RAG can be built without re-ingesting:
uploads learn which account they came from, what date range they cover, and
where the raw original file is stored; sync_jobs learn report type, endpoint,
and date range; traffic tables learn the source file line number per row.
All columns nullable; no data rewrite needed.

Revision ID: c7d2e5a91f04
Revises: b3f1a92c4e18
Create Date: 2026-07-04

"""

import sqlalchemy as sa
from alembic import op

revision = "c7d2e5a91f04"
down_revision = "b3f1a92c4e18"
branch_labels = None
depends_on = None

TRAFFIC_TABLES = [
    "ga4_sessions_daily",
    "gsc_performance_daily",
    "gbp_metrics_daily",
    "paid_media_daily",
]


def upgrade() -> None:
    op.add_column("uploads", sa.Column("source_account", sa.String(300), nullable=True))
    op.add_column("uploads", sa.Column("date_start", sa.Date(), nullable=True))
    op.add_column("uploads", sa.Column("date_end", sa.Date(), nullable=True))
    op.add_column("uploads", sa.Column("stored_path", sa.String(1000), nullable=True))

    op.add_column("sync_jobs", sa.Column("report_type", sa.String(200), nullable=True))
    op.add_column("sync_jobs", sa.Column("endpoint", sa.String(500), nullable=True))
    op.add_column("sync_jobs", sa.Column("date_start", sa.Date(), nullable=True))
    op.add_column("sync_jobs", sa.Column("date_end", sa.Date(), nullable=True))

    for table in TRAFFIC_TABLES:
        op.add_column(table, sa.Column("source_line", sa.Integer(), nullable=True))


def downgrade() -> None:
    for table in TRAFFIC_TABLES:
        op.drop_column(table, "source_line")
    for col in ("date_end", "date_start", "endpoint", "report_type"):
        op.drop_column("sync_jobs", col)
    for col in ("stored_path", "date_end", "date_start", "source_account"):
        op.drop_column("uploads", col)
