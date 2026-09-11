"""Organizations, markets, property attributes, content hashes (Phase 19, slice 1b)

New tables organizations, markets, submarkets. Batch mode for the FK
columns added to companies (organization_id) and properties (market_id,
submarket_id) and for property_content's new columns. Backfills: one
default organization (slug "default"); every company -> default org; one
market per distinct property (city, state); properties.market_id and
properties.domain (registrable host of website_url); property_content
content_hash from the normalized body.

Revision ID: b1c2d3e4f5a7
Revises: a9b8c7d6e5f4
Create Date: 2026-09-11

"""

import hashlib
import re
from datetime import datetime, timezone

import sqlalchemy as sa
from alembic import op

revision = "b1c2d3e4f5a7"
down_revision = "a9b8c7d6e5f4"
branch_labels = None
depends_on = None


def _slug(text: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", (text or "").lower()).strip("-")


def _domain(url: str | None) -> str | None:
    if not url:
        return None
    host = url.strip().lower()
    host = host.split("://", 1)[-1].split("/", 1)[0].split("?", 1)[0].split("#", 1)[0]
    host = host.split(":", 1)[0]
    if host.startswith("www."):
        host = host[4:]
    return host or None


def upgrade() -> None:
    op.create_table(
        "organizations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("slug", sa.String(200), nullable=False, unique=True),
        sa.Column("settings", sa.JSON(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
    )
    op.execute(
        "INSERT INTO organizations (id, name, slug, settings, is_active) "
        "VALUES (1, 'Beacon', 'default', NULL, 1)"
    )

    with op.batch_alter_table("companies") as batch_op:
        batch_op.add_column(sa.Column("organization_id", sa.Integer(), nullable=True))
        batch_op.create_foreign_key(
            "fk_companies_organization_id", "organizations", ["organization_id"], ["id"]
        )
    op.execute("UPDATE companies SET organization_id = 1 WHERE organization_id IS NULL")

    op.create_table(
        "markets",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("organization_id", sa.Integer(), sa.ForeignKey("organizations.id"), nullable=True),
        sa.Column("slug", sa.String(200), nullable=False, unique=True),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("city", sa.String(100), nullable=False),
        sa.Column("state", sa.String(2), nullable=False),
        sa.Column("metro_name", sa.String(200), nullable=True),
        sa.Column("lat", sa.Float(), nullable=True),
        sa.Column("lng", sa.Float(), nullable=True),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default="1"),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_index("ix_markets_state_city", "markets", ["state", "city"])
    op.create_index("ix_markets_org", "markets", ["organization_id"])

    op.create_table(
        "submarkets",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("market_id", sa.Integer(), sa.ForeignKey("markets.id"), nullable=False),
        sa.Column("slug", sa.String(200), nullable=False),
        sa.Column("name", sa.String(200), nullable=False),
        sa.Column("neighborhood_aliases", sa.JSON(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now()),
    )
    op.create_index("uq_submarkets_market_slug", "submarkets", ["market_id", "slug"], unique=True)

    with op.batch_alter_table("properties") as batch_op:
        batch_op.add_column(sa.Column("market_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("submarket_id", sa.Integer(), nullable=True))
        batch_op.add_column(sa.Column("address_line1", sa.String(200), nullable=True))
        batch_op.add_column(sa.Column("zip", sa.String(10), nullable=True))
        batch_op.add_column(sa.Column("lat", sa.Float(), nullable=True))
        batch_op.add_column(sa.Column("lng", sa.Float(), nullable=True))
        batch_op.add_column(sa.Column("domain", sa.String(255), nullable=True))
        batch_op.add_column(sa.Column("attributes", sa.JSON(), nullable=True))
        batch_op.add_column(sa.Column("management_company", sa.String(200), nullable=True))
        batch_op.add_column(sa.Column("ownership", sa.String(200), nullable=True))
        batch_op.add_column(sa.Column("known_competitor_domains", sa.JSON(), nullable=True))
        batch_op.create_foreign_key("fk_properties_market_id", "markets", ["market_id"], ["id"])
        batch_op.create_foreign_key(
            "fk_properties_submarket_id", "submarkets", ["submarket_id"], ["id"]
        )

    with op.batch_alter_table("property_content") as batch_op:
        batch_op.add_column(sa.Column("content_hash", sa.String(64), nullable=True))
        batch_op.add_column(sa.Column("hashed_at", sa.DateTime(), nullable=True))
        batch_op.add_column(sa.Column("topics", sa.JSON(), nullable=True))
        batch_op.add_column(sa.Column("content_changed_at", sa.DateTime(), nullable=True))

    # --- Backfills (plain Python over the live connection; tiny tables). ---
    conn = op.get_bind()
    now = datetime.now(timezone.utc).replace(tzinfo=None)

    rows = conn.execute(
        sa.text("SELECT id, city, state, website_url FROM properties")
    ).fetchall()
    slug_to_id: dict[str, int] = {}
    for prop_id, city, state, website_url in rows:
        market_id = None
        if city and state:
            slug = _slug(f"{city}-{state}")
            if slug not in slug_to_id:
                conn.execute(
                    sa.text(
                        "INSERT INTO markets (slug, name, city, state, is_active) "
                        "VALUES (:slug, :name, :city, :state, 1)"
                    ),
                    {"slug": slug, "name": f"{city}, {state.upper()}", "city": city, "state": state.upper()},
                )
                slug_to_id[slug] = conn.execute(
                    sa.text("SELECT id FROM markets WHERE slug = :slug"), {"slug": slug}
                ).scalar()
            market_id = slug_to_id[slug]
        conn.execute(
            sa.text("UPDATE properties SET market_id = :m, domain = :d WHERE id = :i"),
            {"m": market_id, "d": _domain(website_url), "i": prop_id},
        )

    content_rows = conn.execute(sa.text("SELECT id, body FROM property_content")).fetchall()
    for content_id, body in content_rows:
        normalized = " ".join((body or "").split()).lower()
        digest = hashlib.sha256(normalized.encode("utf-8")).hexdigest()
        conn.execute(
            sa.text(
                "UPDATE property_content SET content_hash = :h, hashed_at = :t WHERE id = :i"
            ),
            {"h": digest, "t": now, "i": content_id},
        )


def downgrade() -> None:
    with op.batch_alter_table("property_content") as batch_op:
        for col in ("content_changed_at", "topics", "hashed_at", "content_hash"):
            batch_op.drop_column(col)
    with op.batch_alter_table("properties") as batch_op:
        batch_op.drop_constraint("fk_properties_submarket_id", type_="foreignkey")
        batch_op.drop_constraint("fk_properties_market_id", type_="foreignkey")
        for col in (
            "known_competitor_domains", "ownership", "management_company", "attributes",
            "domain", "lng", "lat", "zip", "address_line1", "submarket_id", "market_id",
        ):
            batch_op.drop_column(col)
    op.drop_table("submarkets")
    op.drop_table("markets")
    with op.batch_alter_table("companies") as batch_op:
        batch_op.drop_constraint("fk_companies_organization_id", type_="foreignkey")
        batch_op.drop_column("organization_id")
    op.drop_table("organizations")
