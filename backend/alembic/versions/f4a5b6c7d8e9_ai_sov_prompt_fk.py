"""AI Share of Voice prompt filter fields (Phase 18A)

Adds topic_id (FK to ai_topics) and free-text filter fields to
ai_visibility_prompts. Batch mode: SQLite requires it for adding an FK
constraint onto an existing table (unlike d1e2f3a4b5c6's plain add_column
work, which touched only new tables and non-FK columns).

Revision ID: f4a5b6c7d8e9
Revises: d1e2f3a4b5c6
Create Date: 2026-08-10

"""

import sqlalchemy as sa
from alembic import op

revision = "f4a5b6c7d8e9"
down_revision = "d1e2f3a4b5c6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    with op.batch_alter_table("ai_visibility_prompts") as batch_op:
        batch_op.add_column(sa.Column("topic_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("audience", sa.String(100), nullable=True))
        batch_op.add_column(sa.Column("persona", sa.String(100), nullable=True))
        batch_op.add_column(sa.Column("location_market", sa.String(100), nullable=True))
        batch_op.add_column(sa.Column("priority", sa.String(20), nullable=True))
        batch_op.add_column(sa.Column("tags", sa.JSON(), nullable=True))
        batch_op.create_foreign_key(
            "fk_ai_visibility_prompts_topic_id", "ai_topics", ["topic_id"], ["id"]
        )


def downgrade() -> None:
    with op.batch_alter_table("ai_visibility_prompts") as batch_op:
        batch_op.drop_constraint("fk_ai_visibility_prompts_topic_id", type_="foreignkey")
        batch_op.drop_column("tags")
        batch_op.drop_column("priority")
        batch_op.drop_column("location_market")
        batch_op.drop_column("persona")
        batch_op.drop_column("audience")
        batch_op.drop_column("topic_id")
