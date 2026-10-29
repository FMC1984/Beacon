"""Rename the default organization from Beacon to CiteRoll

The row was inserted by b1c2d3e4f5a7 under the old product name, so every
database created before the rename still shows "Beacon" in the organization
switcher. The runtime fallback in services/observatory/tenancy.py already
creates it as "CiteRoll"; this brings existing databases in line.

Guarded on the current name so an operator who renamed their organization by
hand keeps the name they chose.

Revision ID: 2c3d4e5f6071
Revises: 1b2c3d4e5f60
Create Date: 2026-10-28

"""

from alembic import op

revision = "2c3d4e5f6071"
down_revision = "1b2c3d4e5f60"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.execute(
        "UPDATE organizations SET name = 'CiteRoll' "
        "WHERE slug = 'default' AND name = 'Beacon'"
    )


def downgrade() -> None:
    op.execute(
        "UPDATE organizations SET name = 'Beacon' "
        "WHERE slug = 'default' AND name = 'CiteRoll'"
    )
