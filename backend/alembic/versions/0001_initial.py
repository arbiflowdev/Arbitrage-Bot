"""initial schema

Revision ID: 0001_initial
Revises:
Create Date: 2026-05-28 00:00:00

Creates the Milestone-1 tables:
    users, api_credentials, products, sku_mappings, logs
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0001_initial"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # --- users ---------------------------------------------------------------
    op.create_table(
        "users",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("email", sa.String(length=320), nullable=False),
        sa.Column("hashed_password", sa.String(length=255), nullable=False),
        sa.Column("full_name", sa.String(length=255), nullable=True),
        sa.Column(
            "role",
            sa.String(length=20),
            nullable=False,
            server_default="user",
        ),
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
        sa.PrimaryKeyConstraint("id", name=op.f("pk_users")),
        sa.UniqueConstraint("email", name=op.f("uq_users_email")),
    )
    op.create_index(op.f("ix_users_email"), "users", ["email"])

    # --- api_credentials -----------------------------------------------------
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

    # --- products ------------------------------------------------------------
    op.create_table(
        "products",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("internal_sku", sa.String(length=128), nullable=False),
        sa.Column("name", sa.String(length=255), nullable=False),
        sa.Column("description", sa.String(length=2000), nullable=True),
        sa.Column("platform", sa.String(length=64), nullable=True),
        sa.Column("region", sa.String(length=64), nullable=True),
        sa.Column("attributes", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
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
        sa.PrimaryKeyConstraint("id", name=op.f("pk_products")),
        sa.UniqueConstraint("internal_sku", name=op.f("uq_products_internal_sku")),
    )
    op.create_index(op.f("ix_products_internal_sku"), "products", ["internal_sku"])
    op.create_index(op.f("ix_products_platform"), "products", ["platform"])
    op.create_index(op.f("ix_products_region"), "products", ["region"])

    # --- sku_mappings --------------------------------------------------------
    op.create_table(
        "sku_mappings",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("product_id", sa.BigInteger(), nullable=False),
        sa.Column("marketplace", sa.String(length=64), nullable=False),
        sa.Column("marketplace_sku", sa.String(length=128), nullable=False),
        sa.Column("marketplace_url", sa.String(length=1024), nullable=True),
        sa.Column("extra", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
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
            name=op.f("fk_sku_mappings_product_id_products"),
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_sku_mappings")),
        sa.UniqueConstraint(
            "marketplace",
            "marketplace_sku",
            name="uq_sku_mappings_marketplace_sku",
        ),
    )
    op.create_index(
        op.f("ix_sku_mappings_product_id"), "sku_mappings", ["product_id"]
    )
    op.create_index(
        op.f("ix_sku_mappings_marketplace"), "sku_mappings", ["marketplace"]
    )

    # --- logs ----------------------------------------------------------------
    op.create_table(
        "logs",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("level", sa.String(length=16), nullable=False),
        sa.Column("source", sa.String(length=128), nullable=False),
        sa.Column("message", sa.String(length=2000), nullable=False),
        sa.Column("context", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
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
        sa.PrimaryKeyConstraint("id", name=op.f("pk_logs")),
    )
    op.create_index(op.f("ix_logs_level"), "logs", ["level"])
    op.create_index(op.f("ix_logs_source"), "logs", ["source"])


def downgrade() -> None:
    op.drop_index(op.f("ix_logs_source"), table_name="logs")
    op.drop_index(op.f("ix_logs_level"), table_name="logs")
    op.drop_table("logs")

    op.drop_index(op.f("ix_sku_mappings_marketplace"), table_name="sku_mappings")
    op.drop_index(op.f("ix_sku_mappings_product_id"), table_name="sku_mappings")
    op.drop_table("sku_mappings")

    op.drop_index(op.f("ix_products_region"), table_name="products")
    op.drop_index(op.f("ix_products_platform"), table_name="products")
    op.drop_index(op.f("ix_products_internal_sku"), table_name="products")
    op.drop_table("products")

    op.drop_index(op.f("ix_api_credentials_provider"), table_name="api_credentials")
    op.drop_table("api_credentials")

    op.drop_index(op.f("ix_users_email"), table_name="users")
    op.drop_table("users")
