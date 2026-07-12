"""rag chunk text hash

Adds rag_chunks.text_hash so the Phase 7 indexer can skip re-embedding
unchanged chunks. Nullable; no data rewrite.

Revision ID: d4e8b7a20c31
Revises: c7d2e5a91f04
Create Date: 2026-07-04

"""

import sqlalchemy as sa
from alembic import op

revision = "d4e8b7a20c31"
down_revision = "c7d2e5a91f04"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("rag_chunks", sa.Column("text_hash", sa.String(64), nullable=True))


def downgrade() -> None:
    op.drop_column("rag_chunks", "text_hash")
