"""property website url

Adds an optional website_url to properties, e.g. for a housing authority's
single shared site (one URL for a property that has no dedicated domain of
its own, per the DCHP use case).

Revision ID: d4e5f6a7b8c9
Revises: c3d4e5f6a7b8
Create Date: 2026-07-05

"""

import sqlalchemy as sa
from alembic import op

revision = "d4e5f6a7b8c9"
down_revision = "c3d4e5f6a7b8"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("properties", sa.Column("website_url", sa.String(1000), nullable=True))


def downgrade() -> None:
    op.drop_column("properties", "website_url")
