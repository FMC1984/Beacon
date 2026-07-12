"""phase 9 registry expansion and rag sync queue

Expands rag_chunks with embedding lineage (source, page, embedding_version,
provider, updated_at) and adds the rag_sync_jobs queue table. All new columns
nullable; no data rewrite.

Revision ID: f2a9c1d34b57
Revises: d4e8b7a20c31
Create Date: 2026-07-05

"""

import sqlalchemy as sa
from alembic import op

revision = "f2a9c1d34b57"
down_revision = "d4e8b7a20c31"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("rag_chunks", sa.Column("source", sa.String(50), nullable=True))
    op.add_column("rag_chunks", sa.Column("page", sa.String(100), nullable=True))
    op.add_column(
        "rag_chunks", sa.Column("embedding_version", sa.String(100), nullable=True)
    )
    op.add_column("rag_chunks", sa.Column("provider", sa.String(50), nullable=True))
    op.add_column("rag_chunks", sa.Column("updated_at", sa.DateTime(), nullable=True))

    op.create_table(
        "rag_sync_jobs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "property_id", sa.Integer(), sa.ForeignKey("properties.id"), nullable=True
        ),
        sa.Column("source", sa.String(50), nullable=True),
        sa.Column("reason", sa.String(200), nullable=False),
        sa.Column(
            "status",
            sa.Enum(
                "queued",
                "running",
                "completed",
                "failed",
                name="rag_sync_status",
                native_enum=False,
            ),
            nullable=False,
        ),
        sa.Column("chunks_total", sa.Integer(), nullable=False),
        sa.Column("chunks_embedded", sa.Integer(), nullable=False),
        sa.Column("chunks_unchanged", sa.Integer(), nullable=False),
        sa.Column("chunks_removed", sa.Integer(), nullable=False),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
    )
    op.create_index(
        "ix_rag_sync_jobs_status", "rag_sync_jobs", ["status", "id"]
    )


def downgrade() -> None:
    op.drop_index("ix_rag_sync_jobs_status", table_name="rag_sync_jobs")
    op.drop_table("rag_sync_jobs")
    for col in ("updated_at", "provider", "embedding_version", "page", "source"):
        op.drop_column("rag_chunks", col)
