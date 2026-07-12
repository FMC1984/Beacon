"""property.property_type (client/site type)

Adds a required property_type to properties (multifamily_apartment |
housing_authority). Existing rows default to multifamily_apartment via the
server_default. Distinct from property_profile.property_type (regulatory type).

Revision ID: b8c9d0e1f2a3
Revises: a7b8c9d0e1f2
Create Date: 2026-07-06

"""

import sqlalchemy as sa
from alembic import op

revision = "b8c9d0e1f2a3"
down_revision = "a7b8c9d0e1f2"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "properties",
        sa.Column(
            "property_type",
            sa.String(50),
            nullable=False,
            server_default="multifamily_apartment",
        ),
    )


def downgrade() -> None:
    op.drop_column("properties", "property_type")
