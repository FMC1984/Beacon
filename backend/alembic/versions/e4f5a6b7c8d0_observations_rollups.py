"""Derived observations, discovered entities, daily rollups, mention semantics (Phase 19, slice 3)

New tables ai_property_observations, ai_discovered_entities,
ai_visibility_daily, ai_cluster_visibility_daily, ai_market_daily (plain
create_table). mentions gains run_id, mention_type, recommended, sentiment,
sentiment_score, context_excerpt (no FK, plain add_column).

Revision ID: e4f5a6b7c8d0
Revises: d3e4f5a6b7c9
Create Date: 2026-09-11

"""

import sqlalchemy as sa
from alembic import op

revision = "e4f5a6b7c8d0"
down_revision = "d3e4f5a6b7c9"
branch_labels = None
depends_on = None

MENTION_COLS = [
    sa.Column("run_id", sa.Integer(), nullable=True),
    sa.Column("mention_type", sa.String(20), nullable=True),
    sa.Column("recommended", sa.Boolean(), nullable=True),
    sa.Column("sentiment", sa.String(10), nullable=True),
    sa.Column("sentiment_score", sa.Float(), nullable=True),
    sa.Column("context_excerpt", sa.Text(), nullable=True),
]


def _counter(name):
    return sa.Column(name, sa.Integer(), nullable=False, server_default="0")


def upgrade() -> None:
    for col in MENTION_COLS:
        op.add_column("mentions", col)

    op.create_table(
        "ai_property_observations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), nullable=True),
        sa.Column("property_id", sa.Integer(), sa.ForeignKey("properties.id"), nullable=False),
        sa.Column("response_id", sa.Integer(), sa.ForeignKey("ai_visibility_queries.id"), nullable=False),
        sa.Column("run_id", sa.Integer(), sa.ForeignKey("ai_runs.id"), nullable=True),
        sa.Column("prompt_id", sa.Integer(), nullable=True),
        sa.Column("cluster_id", sa.Integer(), nullable=True),
        sa.Column("market_id", sa.Integer(), nullable=True),
        sa.Column("platform", sa.String(50), nullable=False),
        sa.Column("provider", sa.String(30), nullable=True),
        sa.Column("observed_at", sa.DateTime(), nullable=False),
        sa.Column("eligible", sa.Boolean(), nullable=False, server_default="1"),
        sa.Column("eligibility_reason", sa.String(60), nullable=True),
        sa.Column("mentioned", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("mention_position", sa.Integer(), nullable=True),
        sa.Column("mention_rank", sa.Integer(), nullable=True),
        sa.Column("mention_confidence", sa.Float(), nullable=True),
        sa.Column("cited", sa.Boolean(), nullable=False, server_default="0"),
        _counter("citation_count"),
        sa.Column("citation_first_order", sa.Integer(), nullable=True),
        sa.Column("matched_citation_ids", sa.JSON(), nullable=True),
        sa.Column("recommended", sa.Boolean(), nullable=True),
        sa.Column("recommendation_method", sa.String(30), nullable=True),
        sa.Column("sentiment", sa.String(10), nullable=True),
        sa.Column("sentiment_score", sa.Float(), nullable=True),
        sa.Column("context_excerpt", sa.Text(), nullable=True),
        _counter("competitor_mentioned_count"),
        _counter("competitor_cited_count"),
        sa.Column("competitor_entity_ids", sa.JSON(), nullable=True),
        _counter("total_citation_count"),
        sa.Column("derivation_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("rolled_up", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_index("uq_ai_property_observations_response_property", "ai_property_observations",
                    ["response_id", "property_id"], unique=True)
    op.create_index("ix_ai_property_observations_property_observed", "ai_property_observations",
                    ["property_id", "observed_at"])
    op.create_index("ix_ai_property_observations_market_observed", "ai_property_observations",
                    ["market_id", "observed_at"])
    op.create_index("ix_ai_property_observations_cluster_property", "ai_property_observations",
                    ["cluster_id", "property_id", "observed_at"])
    op.create_index("ix_ai_property_observations_org_observed", "ai_property_observations",
                    ["organization_id", "observed_at"])
    op.create_index("ix_ai_property_observations_rolled_up", "ai_property_observations", ["rolled_up"])

    op.create_table(
        "ai_discovered_entities",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("market_id", sa.Integer(), sa.ForeignKey("markets.id"), nullable=True),
        sa.Column("organization_id", sa.Integer(), nullable=True),
        sa.Column("normalized_name", sa.String(200), nullable=False),
        sa.Column("display_name", sa.String(200), nullable=False),
        sa.Column("domain", sa.String(255), nullable=True),
        sa.Column("aliases", sa.JSON(), nullable=True),
        sa.Column("entity_kind", sa.String(20), nullable=False, server_default="unknown"),
        sa.Column("first_seen", sa.DateTime(), nullable=True),
        sa.Column("last_seen", sa.DateTime(), nullable=True),
        _counter("mention_count"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_index("uq_ai_discovered_entities_market_name", "ai_discovered_entities",
                    ["market_id", "normalized_name"], unique=True)

    op.create_table(
        "ai_visibility_daily",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("organization_id", sa.Integer(), nullable=True),
        sa.Column("property_id", sa.Integer(), nullable=False),
        sa.Column("platform", sa.String(50), nullable=False),
        _counter("eligible_count"), _counter("mentioned_count"), _counter("cited_count"),
        _counter("recommended_count"), _counter("owned_citation_count"),
        _counter("tracked_citation_count"), _counter("total_citation_count"),
        _counter("property_mention_responses"), _counter("competitor_mention_count"),
        _counter("competitor_win_count"), _counter("sentiment_pos"), _counter("sentiment_neu"),
        _counter("sentiment_neg"), _counter("runs_count"),
        sa.Column("metric_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("rollup_key", sa.String(120), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_index("uq_ai_visibility_daily_key", "ai_visibility_daily", ["rollup_key"], unique=True)
    op.create_index("ix_ai_visibility_daily_property_day", "ai_visibility_daily", ["property_id", "day"])
    op.create_index("ix_ai_visibility_daily_org_day", "ai_visibility_daily", ["organization_id", "day"])

    op.create_table(
        "ai_cluster_visibility_daily",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("property_id", sa.Integer(), nullable=False),
        sa.Column("cluster_id", sa.Integer(), nullable=False),
        _counter("eligible_count"), _counter("mentioned_count"), _counter("cited_count"),
        _counter("recommended_count"), _counter("competitor_mention_count"), _counter("competitor_win_count"),
        sa.Column("metric_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("rollup_key", sa.String(120), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_index("uq_ai_cluster_visibility_daily_key", "ai_cluster_visibility_daily", ["rollup_key"], unique=True)
    op.create_index("ix_ai_cluster_visibility_daily_property_cluster_day", "ai_cluster_visibility_daily",
                    ["property_id", "cluster_id", "day"])

    op.create_table(
        "ai_market_daily",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("market_id", sa.Integer(), nullable=False),
        sa.Column("platform", sa.String(50), nullable=False),
        _counter("runs_count"), _counter("responses_count"), _counter("properties_scored"),
        _counter("citations_count"), _counter("distinct_domains"),
        sa.Column("metric_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("rollup_key", sa.String(120), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_index("uq_ai_market_daily_key", "ai_market_daily", ["rollup_key"], unique=True)
    op.create_index("ix_ai_market_daily_market_day", "ai_market_daily", ["market_id", "day"])


def downgrade() -> None:
    op.drop_table("ai_market_daily")
    op.drop_table("ai_cluster_visibility_daily")
    op.drop_table("ai_visibility_daily")
    op.drop_table("ai_discovered_entities")
    op.drop_table("ai_property_observations")
    for col in reversed(MENTION_COLS):
        op.drop_column("mentions", col.name)
