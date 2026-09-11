"""AI Observatory run ledger, citations, retrieval queries (Phase 19, slice 1a)

New tables ai_runs, ai_citations, ai_search_queries (plain create_table).
ai_visibility_queries gains the run/prompt links and the normalized + raw
provider evidence, and property_id becomes nullable for market-scoped runs;
that needs batch mode (FK onto an existing table + nullability change).
Backfill: prompt_id by (property_id, prompt_text) match, response_hash from
the stored text, run_scope "property". provider stays NULL for legacy rows
(unknown, not guessed).

Revision ID: a9b8c7d6e5f4
Revises: f4a5b6c7d8e9
Create Date: 2026-09-11

"""

import hashlib

import sqlalchemy as sa
from alembic import op

revision = "a9b8c7d6e5f4"
down_revision = "f4a5b6c7d8e9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ai_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), nullable=True),
        sa.Column("prompt_id", sa.Integer(), sa.ForeignKey("ai_visibility_prompts.id"), nullable=True),
        sa.Column("cluster_id", sa.Integer(), nullable=True),
        sa.Column("market_id", sa.Integer(), nullable=True),
        sa.Column("property_id", sa.Integer(), sa.ForeignKey("properties.id"), nullable=True),
        sa.Column("run_scope", sa.String(20), nullable=False, server_default="property"),
        sa.Column("platform", sa.String(50), nullable=False),
        sa.Column("provider", sa.String(30), nullable=False),
        sa.Column("model_requested", sa.String(100), nullable=True),
        sa.Column("model", sa.String(100), nullable=True),
        sa.Column("repeat_index", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("repeat_group_key", sa.String(160), nullable=True),
        sa.Column("job_id", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="running"),
        sa.Column("error_class", sa.String(100), nullable=True),
        sa.Column("error_message", sa.Text(), nullable=True),
        sa.Column("retry_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("latency_ms", sa.Integer(), nullable=True),
        sa.Column("browsed", sa.Boolean(), nullable=True),
        sa.Column("token_input", sa.Integer(), nullable=True),
        sa.Column("token_output", sa.Integer(), nullable=True),
        sa.Column("token_reasoning", sa.Integer(), nullable=True),
        sa.Column("token_cached", sa.Integer(), nullable=True),
        sa.Column("search_operations", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("estimated_cost", sa.Float(), nullable=True),
        sa.Column("pricing_version", sa.String(40), nullable=True),
        sa.Column("response_hash", sa.String(64), nullable=True),
        sa.Column("duplicate_of_run_id", sa.Integer(), nullable=True),
        sa.Column("provider_response_id", sa.String(120), nullable=True),
        sa.Column("location", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
    )
    for name, cols in [
        ("ix_ai_runs_property_started", ["property_id", "started_at"]),
        ("ix_ai_runs_prompt_started", ["prompt_id", "started_at"]),
        ("ix_ai_runs_market_started", ["market_id", "started_at"]),
        ("ix_ai_runs_org_started", ["organization_id", "started_at"]),
        ("ix_ai_runs_status", ["status", "id"]),
        ("ix_ai_runs_provider_started", ["provider", "started_at"]),
        ("ix_ai_runs_response_hash", ["response_hash"]),
        ("ix_ai_runs_repeat_group", ["repeat_group_key"]),
    ]:
        op.create_index(name, "ai_runs", cols)

    with op.batch_alter_table("ai_visibility_queries") as batch_op:
        batch_op.alter_column("property_id", existing_type=sa.Integer(), nullable=True)
        batch_op.add_column(sa.Column("run_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("prompt_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("market_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("organization_id", sa.Integer(), nullable=True))
        batch_op.add_column(
            sa.Column("run_scope", sa.String(20), nullable=False, server_default="property")
        )
        batch_op.add_column(sa.Column("provider", sa.String(30), nullable=True))
        batch_op.add_column(sa.Column("model", sa.String(100), nullable=True))
        batch_op.add_column(sa.Column("response_hash", sa.String(64), nullable=True))
        batch_op.add_column(sa.Column("normalized_response", sa.JSON(), nullable=True))
        batch_op.add_column(sa.Column("raw_provider_payload", sa.LargeBinary(), nullable=True))
        batch_op.add_column(sa.Column("payload_encoding", sa.String(10), nullable=True))
        batch_op.create_foreign_key(
            "fk_ai_visibility_queries_run_id", "ai_runs", ["run_id"], ["id"]
        )
        batch_op.create_foreign_key(
            "fk_ai_visibility_queries_prompt_id", "ai_visibility_prompts", ["prompt_id"], ["id"]
        )
        batch_op.create_index("ix_ai_visibility_queries_run", ["run_id"])
        batch_op.create_index(
            "ix_ai_visibility_queries_prompt_executed", ["prompt_id", "executed_at"]
        )
        batch_op.create_index("ix_ai_visibility_queries_response_hash", ["response_hash"])

    op.create_table(
        "ai_citations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("response_id", sa.Integer(), sa.ForeignKey("ai_visibility_queries.id"), nullable=False),
        sa.Column("run_id", sa.Integer(), sa.ForeignKey("ai_runs.id"), nullable=True),
        sa.Column("organization_id", sa.Integer(), nullable=True),
        sa.Column("market_id", sa.Integer(), nullable=True),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("normalized_url", sa.Text(), nullable=False),
        sa.Column("domain", sa.String(255), nullable=False),
        sa.Column("root_domain", sa.String(255), nullable=False),
        sa.Column("path", sa.String(500), nullable=True),
        sa.Column("title", sa.String(500), nullable=True),
        sa.Column("citation_order", sa.Integer(), nullable=False),
        sa.Column("citation_position", sa.Integer(), nullable=True),
        sa.Column("end_position", sa.Integer(), nullable=True),
        sa.Column("source_type", sa.String(30), nullable=False),
        sa.Column("capture_method", sa.String(30), nullable=False),
        sa.Column("resolved_url", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_index("ix_ai_citations_response", "ai_citations", ["response_id"])
    op.create_index("ix_ai_citations_run", "ai_citations", ["run_id"])
    op.create_index("ix_ai_citations_domain", "ai_citations", ["domain"])
    op.create_index("ix_ai_citations_market_domain", "ai_citations", ["market_id", "domain"])
    op.create_index(
        "uq_ai_citations_response_url_order", "ai_citations",
        ["response_id", "normalized_url", "citation_order"], unique=True,
    )

    op.create_table(
        "ai_search_queries",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("response_id", sa.Integer(), sa.ForeignKey("ai_visibility_queries.id"), nullable=False),
        sa.Column("run_id", sa.Integer(), sa.ForeignKey("ai_runs.id"), nullable=True),
        sa.Column("provider", sa.String(30), nullable=False),
        sa.Column("query_text", sa.Text(), nullable=False),
        sa.Column("query_order", sa.Integer(), nullable=False),
        sa.Column("captured_from", sa.String(60), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_index("ix_ai_search_queries_run", "ai_search_queries", ["run_id"])
    op.create_index("ix_ai_search_queries_response", "ai_search_queries", ["response_id"])

    # Backfill legacy evidence rows. prompt_id by text match (the join the
    # readers already use); response_hash from the stored text.
    op.execute(
        """
        UPDATE ai_visibility_queries
        SET prompt_id = (
            SELECT MIN(p.id) FROM ai_visibility_prompts p
            WHERE p.property_id = ai_visibility_queries.property_id
              AND p.prompt_text = ai_visibility_queries.prompt_text
        )
        WHERE prompt_id IS NULL
        """
    )
    conn = op.get_bind()
    rows = conn.execute(
        sa.text("SELECT id, raw_response_text FROM ai_visibility_queries WHERE response_hash IS NULL")
    ).fetchall()
    for row_id, text in rows:
        digest = hashlib.sha256((text or "").encode("utf-8")).hexdigest()
        conn.execute(
            sa.text("UPDATE ai_visibility_queries SET response_hash = :h WHERE id = :i"),
            {"h": digest, "i": row_id},
        )


def downgrade() -> None:
    op.drop_table("ai_search_queries")
    op.drop_table("ai_citations")
    with op.batch_alter_table("ai_visibility_queries") as batch_op:
        batch_op.drop_index("ix_ai_visibility_queries_response_hash")
        batch_op.drop_index("ix_ai_visibility_queries_prompt_executed")
        batch_op.drop_index("ix_ai_visibility_queries_run")
        batch_op.drop_constraint("fk_ai_visibility_queries_prompt_id", type_="foreignkey")
        batch_op.drop_constraint("fk_ai_visibility_queries_run_id", type_="foreignkey")
        for col in [
            "payload_encoding", "raw_provider_payload", "normalized_response",
            "response_hash", "model", "provider", "run_scope", "organization_id",
            "market_id", "prompt_id", "run_id",
        ]:
            batch_op.drop_column(col)
        batch_op.alter_column("property_id", existing_type=sa.Integer(), nullable=False)
    op.drop_table("ai_runs")
