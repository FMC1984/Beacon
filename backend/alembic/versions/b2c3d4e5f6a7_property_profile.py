"""property profile (operator-asserted property context)

Adds the 1:1 property_profile table. All fields nullable; an unconfigured
property produces honest "unspecified" output. is_regulated null = UNKNOWN.

Revision ID: b2c3d4e5f6a7
Revises: a1b2c3d4e5f6
Create Date: 2026-07-05

"""

import sqlalchemy as sa
from alembic import op

revision = "b2c3d4e5f6a7"
down_revision = "a1b2c3d4e5f6"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "property_profile",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "property_id", sa.Integer(), sa.ForeignKey("properties.id"), nullable=False
        ),
        sa.Column("property_type", sa.String(50), nullable=True),
        sa.Column("target_audience", sa.String(500), nullable=True),
        sa.Column("is_regulated", sa.Boolean(), nullable=True),
        sa.Column("regulatory_programs", sa.JSON(), nullable=True),
        sa.Column("marketing_restriction_flags", sa.JSON(), nullable=True),
        sa.Column("marketing_restriction_notes", sa.Text(), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(),
            server_default=sa.text("(CURRENT_TIMESTAMP)"),
            nullable=False,
        ),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
        sa.UniqueConstraint("property_id", name="uq_property_profile_property"),
    )
    op.create_index(
        "ix_property_profile_property_id", "property_profile", ["property_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_property_profile_property_id", table_name="property_profile")
    op.drop_table("property_profile")
