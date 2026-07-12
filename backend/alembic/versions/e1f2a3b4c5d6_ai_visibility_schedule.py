"""AI Visibility standing prompts + score history

Reusable prompt set (run on a weekly schedule so a property clears the
sample-size gate) and a score-over-time history so AI visibility is a trend,
not a single snapshot.

Revision ID: e1f2a3b4c5d6
Revises: d0e1f2a3b4c5
Create Date: 2026-07-12

"""

import sqlalchemy as sa
from alembic import op

revision = "e1f2a3b4c5d6"
down_revision = "d0e1f2a3b4c5"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "ai_visibility_prompts",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("property_id", sa.Integer(), sa.ForeignKey("properties.id"), nullable=False),
        sa.Column("platform", sa.String(50), nullable=False, server_default="chatgpt"),
        sa.Column("prompt_text", sa.Text(), nullable=False),
        sa.Column("active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_table(
        "ai_visibility_score_history",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("property_id", sa.Integer(), sa.ForeignKey("properties.id"), nullable=False),
        sa.Column("captured_at", sa.DateTime(), nullable=False),
        sa.Column("score", sa.Float(), nullable=True),
        sa.Column("sample_size", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("mention_rate", sa.Float(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
    )
    op.create_index(
        "ix_ai_vis_score_property_captured",
        "ai_visibility_score_history",
        ["property_id", "captured_at"],
    )


def downgrade() -> None:
    op.drop_index("ix_ai_vis_score_property_captured", "ai_visibility_score_history")
    op.drop_table("ai_visibility_score_history")
    op.drop_table("ai_visibility_prompts")
