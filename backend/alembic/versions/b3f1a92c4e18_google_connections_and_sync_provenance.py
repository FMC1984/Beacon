"""google connections and sync provenance

Adds data_connections + sync_jobs (schema support for future Google OAuth
integrations; no OAuth code exists yet by design), and gives every data table
dual provenance: upload_id becomes nullable, sync_job_id is added, and a CHECK
requires at least one of the two.

Revision ID: b3f1a92c4e18
Revises: 829b777c2d7a
Create Date: 2026-07-04

"""

import sqlalchemy as sa
from alembic import op

revision = "b3f1a92c4e18"
down_revision = "829b777c2d7a"
branch_labels = None
depends_on = None

SOURCE_TYPE = sa.Enum(
    "ga4", "gsc", "gbp", "paid_media", "crm", name="source_type", native_enum=False
)

DATA_TABLES = [
    "ga4_sessions_daily",
    "gsc_performance_daily",
    "gbp_metrics_daily",
    "paid_media_daily",
    "crm_leads",
]


def upgrade() -> None:
    op.create_table(
        "data_connections",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("source_type", SOURCE_TYPE, nullable=False),
        sa.Column("account_name", sa.String(length=300), nullable=False),
        sa.Column("external_account_id", sa.String(length=200), nullable=False),
        sa.Column(
            "oauth_status",
            sa.Enum(
                "disconnected",
                "connected",
                "expired",
                "revoked",
                "error",
                name="oauth_status",
                native_enum=False,
            ),
            nullable=False,
        ),
        sa.Column("last_sync_at", sa.DateTime(), nullable=True),
        sa.Column(
            "sync_frequency",
            sa.Enum(
                "manual",
                "hourly",
                "daily",
                "weekly",
                name="sync_frequency",
                native_enum=False,
            ),
            nullable=False,
        ),
        sa.Column(
            "sync_status",
            sa.Enum(
                "idle",
                "syncing",
                "error",
                "disabled",
                name="sync_status",
                native_enum=False,
            ),
            nullable=False,
        ),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(), server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
    )
    op.create_table(
        "sync_jobs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "connection_id",
            sa.Integer(),
            sa.ForeignKey("data_connections.id"),
            nullable=False,
        ),
        sa.Column("source_type", SOURCE_TYPE, nullable=False),
        sa.Column(
            "started_at", sa.DateTime(), server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column(
            "status",
            sa.Enum(
                "running",
                "completed",
                "failed",
                name="sync_job_status",
                native_enum=False,
            ),
            nullable=False,
        ),
        sa.Column("rows_imported", sa.Integer(), nullable=False),
        sa.Column("rows_updated", sa.Integer(), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
    )

    for table in DATA_TABLES:
        with op.batch_alter_table(table) as batch:
            batch.add_column(sa.Column("sync_job_id", sa.Integer(), nullable=True))
            batch.alter_column(
                "upload_id", existing_type=sa.Integer(), nullable=True
            )
            batch.create_foreign_key(
                f"fk_{table}_sync_job", "sync_jobs", ["sync_job_id"], ["id"]
            )
            batch.create_check_constraint(
                f"ck_{table}_provenance",
                "upload_id IS NOT NULL OR sync_job_id IS NOT NULL",
            )


def downgrade() -> None:
    for table in DATA_TABLES:
        with op.batch_alter_table(table) as batch:
            batch.drop_constraint(f"ck_{table}_provenance", type_="check")
            batch.drop_constraint(f"fk_{table}_sync_job", type_="foreignkey")
            batch.drop_column("sync_job_id")
            batch.alter_column(
                "upload_id", existing_type=sa.Integer(), nullable=False
            )
    op.drop_table("sync_jobs")
    op.drop_table("data_connections")
