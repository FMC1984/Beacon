"""Google OAuth connection fields

The Phase 3 data_connections schema anticipated API integrations; this adds
what a live Google connection actually needs: which Beacon property it feeds,
the OAuth refresh token, and which external resource (GA4 property / GSC site)
it pulls from.

Revision ID: d0e1f2a3b4c5
Revises: c9d0e1f2a3b4
Create Date: 2026-07-12

"""

import sqlalchemy as sa
from alembic import op

revision = "d0e1f2a3b4c5"
down_revision = "c9d0e1f2a3b4"
branch_labels = None
depends_on = None


def upgrade() -> None:
    # batch mode: SQLite cannot ALTER in a foreign-key constraint directly.
    with op.batch_alter_table("data_connections") as batch:
        batch.add_column(sa.Column("property_id", sa.Integer(), nullable=True))
        batch.add_column(sa.Column("refresh_token", sa.Text(), nullable=True))
        batch.add_column(sa.Column("resource_id", sa.String(300), nullable=True))
        batch.add_column(sa.Column("resource_name", sa.String(300), nullable=True))
        batch.create_foreign_key(
            "fk_data_connections_property_id", "properties", ["property_id"], ["id"]
        )


def downgrade() -> None:
    with op.batch_alter_table("data_connections") as batch:
        batch.drop_constraint("fk_data_connections_property_id", type_="foreignkey")
        batch.drop_column("resource_name")
        batch.drop_column("resource_id")
        batch.drop_column("refresh_token")
        batch.drop_column("property_id")
