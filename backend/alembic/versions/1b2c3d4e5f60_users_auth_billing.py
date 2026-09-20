"""Users, memberships, sessions, invites, password resets, Stripe billing

New tables (plain create_table) plus nora_conversations.organization_id
(batch alter). Backfills: existing Nora conversations belong to the default
organization; the default organization gets a billing override so the
founding client is never gated by a subscription it never needed.

Revision ID: 1b2c3d4e5f60
Revises: 0a1b2c3d4e5f
Create Date: 2026-09-20

"""

import json

import sqlalchemy as sa
from alembic import op

revision = "1b2c3d4e5f60"
down_revision = "0a1b2c3d4e5f"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "users",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("name", sa.String(200), nullable=True),
        sa.Column("password_hash", sa.String(300), nullable=False),
        sa.Column("is_platform_admin", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.true()),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("last_login_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_users_email", "users", ["email"], unique=True)

    op.create_table(
        "org_memberships",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.UniqueConstraint("user_id", "organization_id", name="uq_org_memberships_user_org"),
    )
    op.create_index("ix_org_memberships_user_id", "org_memberships", ["user_id"])
    op.create_index("ix_org_memberships_organization_id", "org_memberships", ["organization_id"])

    op.create_table(
        "sessions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("last_seen_at", sa.DateTime(), nullable=True),
        sa.Column("revoked_at", sa.DateTime(), nullable=True),
        sa.Column("user_agent", sa.String(300), nullable=True),
    )
    op.create_index("ix_sessions_token_hash", "sessions", ["token_hash"], unique=True)
    op.create_index("ix_sessions_user_id", "sessions", ["user_id"])

    op.create_table(
        "invites",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("email", sa.String(320), nullable=False),
        sa.Column("role", sa.String(20), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("created_by_user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=True),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("accepted_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_index("ix_invites_token_hash", "invites", ["token_hash"], unique=True)
    op.create_index("ix_invites_organization_id", "invites", ["organization_id"])

    op.create_table(
        "password_resets",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("user_id", sa.Integer(), sa.ForeignKey("users.id"), nullable=False),
        sa.Column("token_hash", sa.String(64), nullable=False),
        sa.Column("expires_at", sa.DateTime(), nullable=False),
        sa.Column("used_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_index("ix_password_resets_token_hash", "password_resets", ["token_hash"], unique=True)
    op.create_index("ix_password_resets_user_id", "password_resets", ["user_id"])

    op.create_table(
        "stripe_customers",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("stripe_customer_id", sa.String(120), nullable=False),
        sa.Column("email", sa.String(320), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_index("ix_stripe_customers_organization_id", "stripe_customers", ["organization_id"], unique=True)
    op.create_index("ix_stripe_customers_customer_id", "stripe_customers", ["stripe_customer_id"], unique=True)

    op.create_table(
        "subscriptions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("stripe_subscription_id", sa.String(120), nullable=False),
        sa.Column("stripe_customer_id", sa.String(120), nullable=True),
        sa.Column("status", sa.String(40), nullable=False),
        sa.Column("price_id", sa.String(120), nullable=True),
        sa.Column("tier", sa.String(20), nullable=True),
        sa.Column("quantity", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("current_period_end", sa.DateTime(), nullable=True),
        sa.Column("cancel_at_period_end", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("last_invoice_status", sa.String(40), nullable=True),
        sa.Column("raw", sa.JSON(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_subscriptions_stripe_id", "subscriptions", ["stripe_subscription_id"], unique=True)
    op.create_index("ix_subscriptions_organization_id", "subscriptions", ["organization_id"])

    op.create_table(
        "billing_purchases",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=False),
        sa.Column("product", sa.String(40), nullable=False),
        sa.Column("stripe_checkout_session_id", sa.String(160), nullable=False),
        sa.Column("amount_cents", sa.Integer(), nullable=True),
        sa.Column("currency", sa.String(10), nullable=True),
        sa.Column("paid_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_billing_purchases_session", "billing_purchases", ["stripe_checkout_session_id"], unique=True)
    op.create_index("ix_billing_purchases_organization_id", "billing_purchases", ["organization_id"])

    op.create_table(
        "billing_events",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("stripe_event_id", sa.String(120), nullable=False),
        sa.Column("type", sa.String(80), nullable=False),
        sa.Column("organization_id", sa.Integer(), nullable=True),
        sa.Column("status", sa.String(20), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("payload", sa.JSON(), nullable=True),
        sa.Column("received_at", sa.DateTime(), server_default=sa.func.now()),
        sa.Column("processed_at", sa.DateTime(), nullable=True),
    )
    op.create_index("ix_billing_events_stripe_id", "billing_events", ["stripe_event_id"], unique=True)

    with op.batch_alter_table("nora_conversations") as batch_op:
        batch_op.add_column(sa.Column("organization_id", sa.Integer(), nullable=True))

    bind = op.get_bind()
    default_org = bind.execute(
        sa.text("SELECT id, settings FROM organizations WHERE slug = 'default'")
    ).first()
    if default_org is not None:
        org_id, raw_settings = default_org
        bind.execute(
            sa.text("UPDATE nora_conversations SET organization_id = :oid WHERE organization_id IS NULL"),
            {"oid": org_id},
        )
        current = {}
        if raw_settings:
            try:
                current = json.loads(raw_settings) if isinstance(raw_settings, str) else dict(raw_settings)
            except (TypeError, ValueError):
                current = {}
        current.setdefault("billing_override", {"active": True, "reason": "founding client"})
        bind.execute(
            sa.text("UPDATE organizations SET settings = :s WHERE id = :oid"),
            {"s": json.dumps(current), "oid": org_id},
        )


def downgrade() -> None:
    with op.batch_alter_table("nora_conversations") as batch_op:
        batch_op.drop_column("organization_id")
    for table in (
        "billing_events",
        "billing_purchases",
        "subscriptions",
        "stripe_customers",
        "password_resets",
        "invites",
        "sessions",
        "org_memberships",
        "users",
    ):
        op.drop_table(table)
