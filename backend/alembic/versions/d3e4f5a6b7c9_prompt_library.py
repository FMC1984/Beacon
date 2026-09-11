"""Prompt library: clusters, embeddings, assignments, prompt scope/provenance (Phase 19, slice 2)

New tables ai_prompt_clusters, ai_prompt_embeddings, ai_prompt_assignments.
ai_visibility_prompts gains scope, cluster/market links, importance,
provenance and clustering fields, and property_id becomes nullable for
market-scope prompts (batch mode). Backfill: scope "brand", approved,
prompt_hash, organization_id via company, market_id via property.

Revision ID: d3e4f5a6b7c9
Revises: c2d3e4f5a6b8
Create Date: 2026-09-11

"""

import hashlib

import sqlalchemy as sa
from alembic import op

revision = "d3e4f5a6b7c9"
down_revision = "c2d3e4f5a6b8"
branch_labels = None
depends_on = None


def _prompt_hash(text: str) -> str:
    return hashlib.sha256(" ".join((text or "").split()).lower().encode("utf-8")).hexdigest()


def upgrade() -> None:
    op.create_table(
        "ai_prompt_clusters",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), nullable=True),
        sa.Column("market_id", sa.Integer(), sa.ForeignKey("markets.id"), nullable=True),
        sa.Column("property_id", sa.Integer(), sa.ForeignKey("properties.id"), nullable=True),
        sa.Column("scope", sa.String(20), nullable=False),
        sa.Column("label", sa.String(300), nullable=False),
        sa.Column("topic_key", sa.String(60), nullable=True),
        sa.Column("intent", sa.String(50), nullable=True),
        sa.Column("geography", sa.String(100), nullable=True),
        sa.Column("persona", sa.String(100), nullable=True),
        sa.Column("funnel_stage", sa.String(30), nullable=True),
        sa.Column("importance", sa.Integer(), nullable=False, server_default="3"),
        sa.Column("representative_prompt_id", sa.Integer(), nullable=True),
        sa.Column("variant_count", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("centroid", sa.LargeBinary(), nullable=True),
        sa.Column("embedding_model", sa.String(100), nullable=True),
        sa.Column("clustering_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_ai_prompt_clusters_market_topic", "ai_prompt_clusters", ["market_id", "topic_key"])
    op.create_index("ix_ai_prompt_clusters_property", "ai_prompt_clusters", ["property_id"])
    op.create_index("ix_ai_prompt_clusters_org_scope", "ai_prompt_clusters", ["organization_id", "scope"])

    with op.batch_alter_table("ai_visibility_prompts") as batch_op:
        batch_op.alter_column("property_id", existing_type=sa.Integer(), nullable=True)
        batch_op.add_column(sa.Column("organization_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("scope", sa.String(20), nullable=False, server_default="brand"))
        batch_op.add_column(sa.Column("cluster_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("market_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("submarket_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("importance", sa.Integer(), nullable=False, server_default="3"))
        batch_op.add_column(sa.Column("funnel_stage", sa.String(30), nullable=True))
        batch_op.add_column(sa.Column("topic_key", sa.String(60), nullable=True))
        batch_op.add_column(sa.Column("generated_from", sa.JSON(), nullable=True))
        batch_op.add_column(sa.Column("generation_method", sa.String(40), nullable=False, server_default="manual"))
        batch_op.add_column(sa.Column("approved", sa.Boolean(), nullable=False, server_default="1"))
        batch_op.add_column(sa.Column("repeat_count", sa.Integer(), nullable=False, server_default="1"))
        batch_op.add_column(sa.Column("prompt_hash", sa.String(64), nullable=True))
        batch_op.add_column(sa.Column("is_representative", sa.Boolean(), nullable=False, server_default="1"))
        batch_op.add_column(sa.Column("variant_group", sa.String(64), nullable=True))
        batch_op.create_foreign_key(
            "fk_ai_visibility_prompts_cluster_id", "ai_prompt_clusters", ["cluster_id"], ["id"]
        )
        batch_op.create_foreign_key(
            "fk_ai_visibility_prompts_market_id", "markets", ["market_id"], ["id"]
        )
        batch_op.create_index("ix_ai_visibility_prompts_market_scope", ["market_id", "scope", "active"])
        batch_op.create_index("ix_ai_visibility_prompts_cluster", ["cluster_id"])
        batch_op.create_index("ix_ai_visibility_prompts_hash", ["prompt_hash"])

    op.create_table(
        "ai_prompt_embeddings",
        sa.Column("prompt_id", sa.Integer(), sa.ForeignKey("ai_visibility_prompts.id"), primary_key=True),
        sa.Column("model", sa.String(100), nullable=False),
        sa.Column("dim", sa.Integer(), nullable=False),
        sa.Column("vector", sa.LargeBinary(), nullable=False),
        sa.Column("prompt_hash", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
    )

    op.create_table(
        "ai_prompt_assignments",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), nullable=True),
        sa.Column("prompt_id", sa.Integer(), sa.ForeignKey("ai_visibility_prompts.id"), nullable=True),
        sa.Column("cluster_id", sa.Integer(), sa.ForeignKey("ai_prompt_clusters.id"), nullable=True),
        sa.Column("property_id", sa.Integer(), sa.ForeignKey("properties.id"), nullable=True),
        sa.Column("market_id", sa.Integer(), sa.ForeignKey("markets.id"), nullable=True),
        sa.Column("assignment_key", sa.String(120), nullable=False, unique=True),
        sa.Column("tier", sa.String(30), nullable=False, server_default="standard_property"),
        sa.Column("active", sa.Boolean(), nullable=False, server_default="1"),
        sa.Column("source", sa.String(20), nullable=False, server_default="auto"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_index("ix_ai_prompt_assignments_property", "ai_prompt_assignments", ["property_id", "active"])
    op.create_index("ix_ai_prompt_assignments_market", "ai_prompt_assignments", ["market_id", "active"])
    op.create_index("ix_ai_prompt_assignments_cluster", "ai_prompt_assignments", ["cluster_id"])

    # Backfill existing (property-scoped, operator-authored) prompts.
    conn = op.get_bind()
    op.execute(
        """
        UPDATE ai_visibility_prompts SET organization_id = (
            SELECT c.organization_id FROM properties p
            LEFT JOIN companies c ON c.id = p.company_id
            WHERE p.id = ai_visibility_prompts.property_id
        ) WHERE organization_id IS NULL
        """
    )
    op.execute("UPDATE ai_visibility_prompts SET organization_id = 1 WHERE organization_id IS NULL")
    op.execute(
        """
        UPDATE ai_visibility_prompts SET market_id = (
            SELECT p.market_id FROM properties p WHERE p.id = ai_visibility_prompts.property_id
        ) WHERE market_id IS NULL
        """
    )
    rows = conn.execute(sa.text("SELECT id, prompt_text FROM ai_visibility_prompts")).fetchall()
    for prompt_id, text in rows:
        conn.execute(
            sa.text("UPDATE ai_visibility_prompts SET prompt_hash = :h WHERE id = :i"),
            {"h": _prompt_hash(text), "i": prompt_id},
        )


def downgrade() -> None:
    op.drop_table("ai_prompt_assignments")
    op.drop_table("ai_prompt_embeddings")
    with op.batch_alter_table("ai_visibility_prompts") as batch_op:
        batch_op.drop_index("ix_ai_visibility_prompts_hash")
        batch_op.drop_index("ix_ai_visibility_prompts_cluster")
        batch_op.drop_index("ix_ai_visibility_prompts_market_scope")
        batch_op.drop_constraint("fk_ai_visibility_prompts_market_id", type_="foreignkey")
        batch_op.drop_constraint("fk_ai_visibility_prompts_cluster_id", type_="foreignkey")
        for col in (
            "variant_group", "is_representative", "prompt_hash", "repeat_count", "approved",
            "generation_method", "generated_from", "topic_key", "funnel_stage", "importance",
            "submarket_id", "market_id", "cluster_id", "scope", "organization_id",
        ):
            batch_op.drop_column(col)
        batch_op.alter_column("property_id", existing_type=sa.Integer(), nullable=False)
    op.drop_table("ai_prompt_clusters")
