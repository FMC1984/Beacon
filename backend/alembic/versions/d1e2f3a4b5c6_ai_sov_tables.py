"""AI Share of Voice tables (Phase 18A)

New tables: ai_topics, mentions, ai_sov_snapshots. Plain add_column (no FK)
for properties.aliases and the five new ai_visibility_queries columns. No
batch mode needed - new tables and non-FK columns only.

Revision ID: d1e2f3a4b5c6
Revises: c3e4f5a6b7d8
Create Date: 2026-08-10

"""

import sqlalchemy as sa
from alembic import op

revision = "d1e2f3a4b5c6"
down_revision = "c3e4f5a6b7d8"
branch_labels = None
depends_on = None

QUERY_COLS = [
    sa.Column("execution_status", sa.String(20), nullable=False, server_default="success"),
    sa.Column("error_message", sa.Text(), nullable=True),
    sa.Column("model_metadata", sa.JSON(), nullable=True),
    sa.Column("property_mention_count", sa.Integer(), nullable=False, server_default="0"),
    sa.Column("competitor_mention_count", sa.Integer(), nullable=False, server_default="0"),
]


def upgrade() -> None:
    op.add_column("properties", sa.Column("aliases", sa.JSON(), nullable=True))

    for col in QUERY_COLS:
        op.add_column("ai_visibility_queries", col)

    op.create_table(
        "ai_topics",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("property_id", sa.Integer(), sa.ForeignKey("properties.id"), nullable=False),
        sa.Column("topic_name", sa.String(200), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("priority", sa.String(20), nullable=False, server_default="medium"),
        sa.Column("status", sa.String(20), nullable=False, server_default="active"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
    )
    op.create_index("uq_ai_topic_name", "ai_topics", ["property_id", "topic_name"], unique=True)
    op.create_index("ix_ai_topic_property", "ai_topics", ["property_id"])

    op.create_table(
        "mentions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("response_id", sa.Integer(), sa.ForeignKey("ai_visibility_queries.id"), nullable=False),
        sa.Column("entity_type", sa.String(20), nullable=False),
        sa.Column("entity_id", sa.Integer(), nullable=False),
        sa.Column("normalized_name", sa.String(200), nullable=False),
        sa.Column("raw_matched_text", sa.String(200), nullable=False),
        sa.Column("match_count", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("position", sa.Integer(), nullable=True),
        sa.Column("confidence", sa.Float(), nullable=False, server_default="1.0"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_index("ix_mention_response", "mentions", ["response_id"])
    op.create_index("ix_mention_entity", "mentions", ["entity_type", "entity_id"])

    op.create_table(
        "ai_sov_snapshots",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("property_id", sa.Integer(), sa.ForeignKey("properties.id"), nullable=False),
        sa.Column("topic_id", sa.Integer(), sa.ForeignKey("ai_topics.id"), nullable=True),
        sa.Column("platform", sa.String(50), nullable=True),
        sa.Column("period_start", sa.Date(), nullable=False),
        sa.Column("period_end", sa.Date(), nullable=False),
        sa.Column("captured_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("property_mentions", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("competitor_mentions", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("sample_size", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("sufficient", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("share_of_voice", sa.Float(), nullable=True),
        sa.Column("rank", sa.Integer(), nullable=True),
        sa.Column("rank_of", sa.Integer(), nullable=True),
    )
    op.create_index(
        "uq_sov_snapshot", "ai_sov_snapshots",
        ["property_id", "topic_id", "platform", "period_start", "period_end"],
        unique=True,
    )
    op.create_index(
        "ix_sov_snapshot_property_captured", "ai_sov_snapshots",
        ["property_id", "captured_at"],
    )


def downgrade() -> None:
    op.drop_table("ai_sov_snapshots")
    op.drop_table("mentions")
    op.drop_table("ai_topics")
    for col in reversed(QUERY_COLS):
        op.drop_column("ai_visibility_queries", col.name)
    op.drop_column("properties", "aliases")
