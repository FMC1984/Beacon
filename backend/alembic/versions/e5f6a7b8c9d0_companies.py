"""companies + property.company_id

Adds a Company layer above properties. A company groups multiple properties;
a property may belong to one company or none (company_id nullable = the
'Unassigned' bucket in the UI). Deleting a company unassigns its properties
rather than deleting them (handled in the router, not by DB cascade).

Revision ID: e5f6a7b8c9d0
Revises: d4e5f6a7b8c9
Create Date: 2026-07-05

"""

import sqlalchemy as sa
from alembic import op

revision = "e5f6a7b8c9d0"
down_revision = "d4e5f6a7b8c9"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "companies",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("slug", sa.String(200), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.func.now(),
            nullable=False,
        ),
        sa.UniqueConstraint("name", name="uq_companies_name"),
        sa.UniqueConstraint("slug", name="uq_companies_slug"),
    )
    with op.batch_alter_table("properties") as batch:
        batch.add_column(sa.Column("company_id", sa.Integer(), nullable=True))
        batch.create_foreign_key(
            "fk_properties_company_id",
            "companies",
            ["company_id"],
            ["id"],
        )


def downgrade() -> None:
    with op.batch_alter_table("properties") as batch:
        batch.drop_constraint("fk_properties_company_id", type_="foreignkey")
        batch.drop_column("company_id")
    op.drop_table("companies")
