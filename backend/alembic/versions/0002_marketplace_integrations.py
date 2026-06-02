"""marketplace integrations

Revision ID: 0002_marketplace_integrations
Revises: 0001_initial
Create Date: 2026-06-01 00:00:00

Milestone-2 schema:
    * drop api_credentials (credentials now live in .env only)
    * marketplace_prices
    * listings
    * webhook_events
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0002_marketplace_integrations"
down_revision: str | None = "0001_initial"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # --- api_credentials: removed (credentials now supplied via .env only) ---
    op.drop_index(
        op.f("ix_api_credentials_provider"), table_name="api_credentials"
    )
    op.drop_table("api_credentials")

    # --- marketplace_prices --------------------------------------------------
    op.create_table(
        "marketplace_prices",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("marketplace_sku", sa.String(length=128), nullable=False),
        sa.Column("product_id", sa.BigInteger(), nullable=True),
        sa.Column(
            "currency", sa.String(length=3), nullable=False, server_default="EUR"
        ),
        sa.Column("price", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("available_qty", sa.Integer(), nullable=True),
        sa.Column(
            "is_available",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column("raw", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "fetched_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(
            ["product_id"],
            ["products.id"],
            name=op.f("fk_marketplace_prices_product_id_products"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_marketplace_prices")),
        sa.UniqueConstraint(
            "provider",
            "marketplace_sku",
            name="uq_marketplace_prices_provider_sku",
        ),
    )
    op.create_index(
        op.f("ix_marketplace_prices_provider"), "marketplace_prices", ["provider"]
    )
    op.create_index(
        op.f("ix_marketplace_prices_marketplace_sku"),
        "marketplace_prices",
        ["marketplace_sku"],
    )
    op.create_index(
        op.f("ix_marketplace_prices_product_id"),
        "marketplace_prices",
        ["product_id"],
    )

    # --- listings ------------------------------------------------------------
    op.create_table(
        "listings",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("marketplace_sku", sa.String(length=128), nullable=False),
        sa.Column("external_listing_id", sa.String(length=128), nullable=True),
        sa.Column("product_id", sa.BigInteger(), nullable=True),
        sa.Column("title", sa.String(length=255), nullable=True),
        sa.Column("price", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column("currency", sa.String(length=3), nullable=True),
        sa.Column("stock", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "status",
            sa.String(length=16),
            nullable=False,
            server_default="draft",
        ),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sync_error", sa.String(length=1024), nullable=True),
        sa.Column("raw", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(
            ["product_id"],
            ["products.id"],
            name=op.f("fk_listings_product_id_products"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_listings")),
        sa.UniqueConstraint(
            "provider", "marketplace_sku", name="uq_listings_provider_sku"
        ),
    )
    op.create_index(op.f("ix_listings_provider"), "listings", ["provider"])
    op.create_index(
        op.f("ix_listings_marketplace_sku"), "listings", ["marketplace_sku"]
    )
    op.create_index(
        op.f("ix_listings_external_listing_id"),
        "listings",
        ["external_listing_id"],
    )
    op.create_index(op.f("ix_listings_product_id"), "listings", ["product_id"])
    op.create_index(op.f("ix_listings_status"), "listings", ["status"])

    # --- webhook_events ------------------------------------------------------
    op.create_table(
        "webhook_events",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("event_type", sa.String(length=128), nullable=False),
        sa.Column("external_id", sa.String(length=255), nullable=True),
        sa.Column(
            "signature_valid",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "status",
            sa.String(length=16),
            nullable=False,
            server_default="received",
        ),
        sa.Column("payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("headers", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("error", sa.String(length=1024), nullable=True),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_webhook_events")),
        sa.UniqueConstraint(
            "provider",
            "external_id",
            name="uq_webhook_events_provider_external_id",
        ),
    )
    op.create_index(
        op.f("ix_webhook_events_provider"), "webhook_events", ["provider"]
    )
    op.create_index(
        op.f("ix_webhook_events_event_type"), "webhook_events", ["event_type"]
    )
    op.create_index(
        op.f("ix_webhook_events_status"), "webhook_events", ["status"]
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_webhook_events_status"), table_name="webhook_events")
    op.drop_index(op.f("ix_webhook_events_event_type"), table_name="webhook_events")
    op.drop_index(op.f("ix_webhook_events_provider"), table_name="webhook_events")
    op.drop_table("webhook_events")

    op.drop_index(op.f("ix_listings_status"), table_name="listings")
    op.drop_index(op.f("ix_listings_product_id"), table_name="listings")
    op.drop_index(op.f("ix_listings_external_listing_id"), table_name="listings")
    op.drop_index(op.f("ix_listings_marketplace_sku"), table_name="listings")
    op.drop_index(op.f("ix_listings_provider"), table_name="listings")
    op.drop_table("listings")

    op.drop_index(
        op.f("ix_marketplace_prices_product_id"), table_name="marketplace_prices"
    )
    op.drop_index(
        op.f("ix_marketplace_prices_marketplace_sku"),
        table_name="marketplace_prices",
    )
    op.drop_index(
        op.f("ix_marketplace_prices_provider"), table_name="marketplace_prices"
    )
    op.drop_table("marketplace_prices")

    # Recreate api_credentials as it was defined in 0001_initial.
    op.create_table(
        "api_credentials",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column(
            "label",
            sa.String(length=128),
            nullable=False,
            server_default="default",
        ),
        sa.Column("api_key", sa.String(length=1024), nullable=True),
        sa.Column("api_secret", sa.String(length=1024), nullable=True),
        sa.Column("extra", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column(
            "is_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("true"),
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at",
            sa.DateTime(timezone=True),
            nullable=False,
            server_default=sa.func.now(),
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_api_credentials")),
        sa.UniqueConstraint(
            "provider", "label", name="uq_api_credentials_provider_label"
        ),
    )
    op.create_index(
        op.f("ix_api_credentials_provider"), "api_credentials", ["provider"]
    )
