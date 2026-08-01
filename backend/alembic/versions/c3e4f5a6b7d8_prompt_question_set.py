"""AI Visibility prompt question-set metadata (DCHP seed import)

Cadence-aware standing prompts with operator-asserted success criteria:
cadence + runs_per_cycle drive the scheduler, owning_url/must_contain/
volatile/notes carry the question-set audit metadata, last_run_at tracks
due-ness. Plain add_column (no FK), so no batch mode needed.

Revision ID: c3e4f5a6b7d8
Revises: b2d3f4a5c6e7
Create Date: 2026-08-01

"""

import sqlalchemy as sa
from alembic import op

revision = "c3e4f5a6b7d8"
down_revision = "b2d3f4a5c6e7"
branch_labels = None
depends_on = None

COLS = [
    sa.Column("cadence", sa.String(20), nullable=False, server_default="weekly"),
    sa.Column("runs_per_cycle", sa.Integer(), nullable=False, server_default="1"),
    sa.Column("intent", sa.String(50), nullable=True),
    sa.Column("owning_url", sa.String(500), nullable=True),
    sa.Column("volatile", sa.Boolean(), nullable=False, server_default="0"),
    sa.Column("must_contain", sa.JSON(), nullable=True),
    sa.Column("notes", sa.Text(), nullable=True),
    sa.Column("last_run_at", sa.DateTime(), nullable=True),
]


def upgrade() -> None:
    for col in COLS:
        op.add_column("ai_visibility_prompts", col)


def downgrade() -> None:
    for col in reversed(COLS):
        op.drop_column("ai_visibility_prompts", col.name)
