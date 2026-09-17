"""Rename the "IQ" module labels inside saved briefing snapshots

Content IQ / Review IQ / Competitor IQ became Content Analysis / Review
Analysis / Competitor Analysis. Saved monthly briefings freeze their payload
(and shared briefing links render it), so the old labels are rewritten in
place. Data only; no schema change. Done in Python so it is dialect-neutral.

Revision ID: d9e0f1a2b3c4
Revises: c8d9e0f1a2b3
Create Date: 2026-09-17

"""

import json

import sqlalchemy as sa
from alembic import op

revision = "d9e0f1a2b3c4"
down_revision = "c8d9e0f1a2b3"
branch_labels = None
depends_on = None

RENAMES = (
    ("Content IQ", "Content Analysis"),
    ("Review IQ", "Review Analysis"),
    ("Competitor IQ", "Competitor Analysis"),
)


def rewrite(text: str) -> str:
    for old, new in RENAMES:
        text = text.replace(old, new)
    return text


def upgrade() -> None:
    bind = op.get_bind()
    if "monthly_briefings" not in sa.inspect(bind).get_table_names():
        return
    rows = bind.execute(sa.text("SELECT id, payload FROM monthly_briefings")).fetchall()
    for row_id, payload in rows:
        raw = payload if isinstance(payload, str) else json.dumps(payload)
        new = rewrite(raw)
        if new != raw:
            bind.execute(sa.text("UPDATE monthly_briefings SET payload = :p WHERE id = :i"), {"p": new, "i": row_id})


def downgrade() -> None:
    # Labels only; the old names are intentionally not restored.
    pass
