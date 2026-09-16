"""Observatory scale rollups: source domains, run costs, competitor stats (Phase 19)

Three new tables (plain create_table). They cache what is computed live from
ai_citations, ai_runs and ai_property_observations; the live computation
stays the source of truth and a reconciliation test holds them equal.

Revision ID: b7c8d9e0f1a2
Revises: a6b7c8d9e0f3
Create Date: 2026-09-16

"""

import sqlalchemy as sa
from alembic import op

revision = "b7c8d9e0f1a2"
down_revision = "a6b7c8d9e0f3"
branch_labels = None
depends_on = None


def _counter(name):
    return sa.Column(name, sa.Integer(), nullable=False, server_default="0")


def upgrade() -> None:
    op.create_table(
        "ai_source_domains",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), nullable=True),
        sa.Column("property_id", sa.Integer(), nullable=True),
        sa.Column("market_id", sa.Integer(), nullable=True),
        sa.Column("period", sa.String(20), nullable=False),
        sa.Column("period_kind", sa.String(10), nullable=False, server_default="window"),
        sa.Column("window_start", sa.Date(), nullable=False),
        sa.Column("window_end", sa.Date(), nullable=False),
        sa.Column("domain", sa.String(255), nullable=False),
        sa.Column("source_type", sa.String(40), nullable=True),
        _counter("citations"), _counter("responses"),
        sa.Column("share", sa.Float(), nullable=True),
        sa.Column("rollup_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("rollup_key", sa.String(200), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_index("uq_ai_source_domains_key", "ai_source_domains", ["rollup_key"], unique=True)
    op.create_index("ix_ai_source_domains_scope", "ai_source_domains", ["property_id", "period", "citations"])

    op.create_table(
        "ai_run_costs_daily",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("organization_id", sa.Integer(), nullable=True),
        sa.Column("provider", sa.String(30), nullable=True),
        sa.Column("model", sa.String(100), nullable=True),
        sa.Column("run_scope", sa.String(20), nullable=True),
        _counter("runs"), _counter("runs_success"), _counter("runs_failed"), _counter("runs_discarded"),
        _counter("priced_runs"), _counter("token_input"), _counter("token_output"),
        _counter("token_reasoning"), _counter("token_cached"), _counter("search_operations"),
        sa.Column("estimated_usd", sa.Float(), nullable=True),
        _counter("observations"),
        sa.Column("rollup_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("rollup_key", sa.String(200), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_index("uq_ai_run_costs_daily_key", "ai_run_costs_daily", ["rollup_key"], unique=True)
    op.create_index("ix_ai_run_costs_daily_org_day", "ai_run_costs_daily", ["organization_id", "day"])

    op.create_table(
        "ai_competitor_stats",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), nullable=True),
        sa.Column("property_id", sa.Integer(), nullable=False),
        sa.Column("competitor_id", sa.Integer(), nullable=False),
        sa.Column("competitor_name", sa.String(200), nullable=False),
        sa.Column("period", sa.String(20), nullable=False),
        sa.Column("window_start", sa.Date(), nullable=False),
        sa.Column("window_end", sa.Date(), nullable=False),
        _counter("shared_responses"), _counter("competitor_mentions"), _counter("property_mentions"),
        _counter("co_mentions"), _counter("competitor_wins"), _counter("property_wins"),
        _counter("competitor_citations"), _counter("property_citations"),
        sa.Column("co_mention_rate", sa.Float(), nullable=True),
        sa.Column("competitor_win_rate", sa.Float(), nullable=True),
        sa.Column("citation_share", sa.Float(), nullable=True),
        sa.Column("rollup_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("rollup_key", sa.String(200), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_index("uq_ai_competitor_stats_key", "ai_competitor_stats", ["rollup_key"], unique=True)
    op.create_index("ix_ai_competitor_stats_property", "ai_competitor_stats", ["property_id", "period"])


def downgrade() -> None:
    op.drop_table("ai_competitor_stats")
    op.drop_table("ai_run_costs_daily")
    op.drop_table("ai_source_domains")
