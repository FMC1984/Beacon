"""rag_chunks.enrichment (semantic metadata)

Adds the nullable JSON enrichment column to the RAG chunk registry (Phase 15a).
Holds the deterministic semantic metadata (topics, entities, intents, per-topic
sentiment, normalized terms, matched rules) computed at index time. Metadata
only - chunk text is never replaced. Null means the chunk was indexed before
enrichment existed; the next sync fills it in.

Revision ID: c9d0e1f2a3b4
Revises: b8c9d0e1f2a3
Create Date: 2026-07-08

"""

import sqlalchemy as sa
from alembic import op

revision = "c9d0e1f2a3b4"
down_revision = "b8c9d0e1f2a3"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("rag_chunks", sa.Column("enrichment", sa.JSON(), nullable=True))


def downgrade() -> None:
    op.drop_column("rag_chunks", "enrichment")
