"""Discovery decisions, claims, alerts, run schedule, schedule decisions (Phase 19, slice 5)

New tables ai_entity_decisions, ai_claims, ai_visibility_alerts,
ai_run_schedule, ai_schedule_decisions (plain create_table).
ai_discovered_entities gains response_count, evidence_response_ids,
sample_context (plain add_column, no FK).

Revision ID: f5a6b7c8d9e1
Revises: e4f5a6b7c8d0
Create Date: 2026-09-12

"""

import sqlalchemy as sa
from alembic import op

revision = "f5a6b7c8d9e1"
down_revision = "e4f5a6b7c8d0"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("ai_discovered_entities", sa.Column("response_count", sa.Integer(), nullable=False, server_default="0"))
    op.add_column("ai_discovered_entities", sa.Column("evidence_response_ids", sa.JSON(), nullable=True))
    op.add_column("ai_discovered_entities", sa.Column("sample_context", sa.Text(), nullable=True))

    op.create_table(
        "ai_entity_decisions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("entity_id", sa.Integer(), sa.ForeignKey("ai_discovered_entities.id"), nullable=False),
        sa.Column("property_id", sa.Integer(), sa.ForeignKey("properties.id"), nullable=False),
        sa.Column("decision", sa.String(20), nullable=False),
        sa.Column("competitor_id", sa.Integer(), nullable=True),
        sa.Column("decided_at", sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_index("uq_ai_entity_decisions_entity_property", "ai_entity_decisions", ["entity_id", "property_id"], unique=True)

    op.create_table(
        "ai_claims",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), nullable=True),
        sa.Column("property_id", sa.Integer(), sa.ForeignKey("properties.id"), nullable=False),
        sa.Column("claim_type", sa.String(40), nullable=False),
        sa.Column("claim_topic", sa.String(60), nullable=True),
        sa.Column("claim_value", sa.String(200), nullable=False),
        sa.Column("claim_text", sa.Text(), nullable=False),
        sa.Column("verification_status", sa.String(30), nullable=False),
        sa.Column("verification_method", sa.String(60), nullable=False),
        sa.Column("evidence", sa.Text(), nullable=False),
        sa.Column("known_value", sa.String(200), nullable=True),
        sa.Column("severity", sa.String(10), nullable=False, server_default="low"),
        sa.Column("claim_hash", sa.String(64), nullable=False),
        sa.Column("first_seen", sa.DateTime(), nullable=False),
        sa.Column("last_seen", sa.DateTime(), nullable=False),
        sa.Column("occurrence_count", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("response_ids", sa.JSON(), nullable=True),
        sa.Column("platforms", sa.JSON(), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="open"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
    )
    op.create_index("uq_ai_claims_property_hash", "ai_claims", ["property_id", "claim_hash"], unique=True)
    op.create_index("ix_ai_claims_property_status", "ai_claims", ["property_id", "verification_status"])

    op.create_table(
        "ai_visibility_alerts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), nullable=True),
        sa.Column("property_id", sa.Integer(), nullable=True),
        sa.Column("market_id", sa.Integer(), nullable=True),
        sa.Column("alert_type", sa.String(40), nullable=False),
        sa.Column("severity", sa.String(10), nullable=False),
        sa.Column("title", sa.String(300), nullable=False),
        sa.Column("detail", sa.Text(), nullable=False),
        sa.Column("evidence", sa.JSON(), nullable=True),
        sa.Column("metric_before", sa.Float(), nullable=True),
        sa.Column("metric_after", sa.Float(), nullable=True),
        sa.Column("data_label", sa.String(20), nullable=False, server_default="MEASURED"),
        sa.Column("status", sa.String(20), nullable=False, server_default="open"),
        sa.Column("dedupe_key", sa.String(200), nullable=False),
        sa.Column("escalated", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
    )
    op.create_index("uq_ai_visibility_alerts_dedupe", "ai_visibility_alerts", ["dedupe_key"], unique=True)
    op.create_index("ix_ai_visibility_alerts_property_status", "ai_visibility_alerts", ["property_id", "status"])

    op.create_table(
        "ai_run_schedule",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), nullable=True),
        sa.Column("prompt_id", sa.Integer(), sa.ForeignKey("ai_visibility_prompts.id"), nullable=False),
        sa.Column("cluster_id", sa.Integer(), nullable=True),
        sa.Column("property_id", sa.Integer(), nullable=True),
        sa.Column("market_id", sa.Integer(), nullable=True),
        sa.Column("platform", sa.String(50), nullable=False),
        sa.Column("tier", sa.String(30), nullable=False),
        sa.Column("tier_override", sa.String(30), nullable=True),
        sa.Column("escalation_until", sa.DateTime(), nullable=True),
        sa.Column("cadence_days", sa.Integer(), nullable=False),
        sa.Column("repeat_count", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("next_run_at", sa.DateTime(), nullable=True),
        sa.Column("last_run_at", sa.DateTime(), nullable=True),
        sa.Column("last_priority_score", sa.Float(), nullable=True),
        sa.Column("priority_components", sa.JSON(), nullable=True),
        sa.Column("status", sa.String(20), nullable=False, server_default="active"),
        sa.Column("schedule_key", sa.String(200), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
    )
    op.create_index("uq_ai_run_schedule_key", "ai_run_schedule", ["schedule_key"], unique=True)
    op.create_index("ix_ai_run_schedule_next", "ai_run_schedule", ["status", "next_run_at"])

    op.create_table(
        "ai_schedule_decisions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("plan_key", sa.String(100), nullable=False),
        sa.Column("schedule_id", sa.Integer(), nullable=True),
        sa.Column("prompt_id", sa.Integer(), nullable=True),
        sa.Column("decision", sa.String(30), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("priority_score", sa.Float(), nullable=True),
        sa.Column("priority_components", sa.JSON(), nullable=True),
        sa.Column("job_ids", sa.JSON(), nullable=True),
        sa.Column("dry_run", sa.Boolean(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_index("ix_ai_schedule_decisions_plan", "ai_schedule_decisions", ["plan_key", "id"])


def downgrade() -> None:
    op.drop_table("ai_schedule_decisions")
    op.drop_table("ai_run_schedule")
    op.drop_table("ai_visibility_alerts")
    op.drop_table("ai_claims")
    op.drop_table("ai_entity_decisions")
    op.drop_column("ai_discovered_entities", "sample_context")
    op.drop_column("ai_discovered_entities", "evidence_response_ids")
    op.drop_column("ai_discovered_entities", "response_count")
