"""hybrid inventory & JIT fulfillment

Revision ID: 0004_fulfillment
Revises: 0003_pricing_engine
Create Date: 2026-06-06 00:00:00

Milestone-4 schema:
    * inventory        - deliverable codes/keys we hold in stock
    * orders           - customer sales to fulfill (inventory-first / JIT)
    * transactions     - signed money + delivery ledger
    * wallet_balances  - per-marketplace funds for JIT purchases
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0004_fulfillment"
down_revision: str | None = "0003_pricing_engine"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _timestamps() -> list[sa.Column]:
    return [
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
    ]


def upgrade() -> None:
    # --- inventory -----------------------------------------------------------
    op.create_table(
        "inventory",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("product_id", sa.BigInteger(), nullable=True),
        sa.Column("code", sa.String(length=512), nullable=False),
        sa.Column(
            "status",
            sa.String(length=16),
            nullable=False,
            server_default="available",
        ),
        sa.Column("region", sa.String(length=64), nullable=True),
        sa.Column("platform", sa.String(length=64), nullable=True),
        sa.Column("source_cost", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column("currency", sa.String(length=3), nullable=True),
        sa.Column("reserved_order_id", sa.BigInteger(), nullable=True),
        sa.Column("reserved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sold_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("batch_id", sa.String(length=64), nullable=True),
        sa.Column("notes", sa.String(length=512), nullable=True),
        sa.Column("raw", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(
            ["product_id"],
            ["products.id"],
            name=op.f("fk_inventory_product_id_products"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_inventory")),
    )
    op.create_index(op.f("ix_inventory_product_id"), "inventory", ["product_id"])
    op.create_index(op.f("ix_inventory_status"), "inventory", ["status"])
    op.create_index(
        op.f("ix_inventory_reserved_order_id"), "inventory", ["reserved_order_id"]
    )
    op.create_index(op.f("ix_inventory_batch_id"), "inventory", ["batch_id"])

    # --- orders --------------------------------------------------------------
    op.create_table(
        "orders",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("external_order_id", sa.String(length=128), nullable=False),
        sa.Column("marketplace_sku", sa.String(length=128), nullable=False),
        sa.Column("product_id", sa.BigInteger(), nullable=True),
        sa.Column("quantity", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("total", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column("currency", sa.String(length=3), nullable=True),
        sa.Column(
            "status", sa.String(length=20), nullable=False, server_default="received"
        ),
        sa.Column("fulfillment_source", sa.String(length=16), nullable=True),
        sa.Column("inventory_id", sa.BigInteger(), nullable=True),
        sa.Column("attempts", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_error", sa.String(length=1024), nullable=True),
        sa.Column("received_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("raw", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(
            ["product_id"],
            ["products.id"],
            name=op.f("fk_orders_product_id_products"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["inventory_id"],
            ["inventory.id"],
            name=op.f("fk_orders_inventory_id_inventory"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_orders")),
        sa.UniqueConstraint(
            "provider", "external_order_id", name="uq_orders_provider_external_id"
        ),
    )
    op.create_index(op.f("ix_orders_provider"), "orders", ["provider"])
    op.create_index(
        op.f("ix_orders_external_order_id"), "orders", ["external_order_id"]
    )
    op.create_index(op.f("ix_orders_marketplace_sku"), "orders", ["marketplace_sku"])
    op.create_index(op.f("ix_orders_product_id"), "orders", ["product_id"])
    op.create_index(op.f("ix_orders_inventory_id"), "orders", ["inventory_id"])
    op.create_index(op.f("ix_orders_status"), "orders", ["status"])

    # --- transactions --------------------------------------------------------
    op.create_table(
        "transactions",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("order_id", sa.BigInteger(), nullable=True),
        sa.Column("type", sa.String(length=16), nullable=False),
        sa.Column("provider", sa.String(length=64), nullable=True),
        sa.Column("amount", sa.Numeric(precision=14, scale=2), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column("balance_after", sa.Numeric(precision=14, scale=2), nullable=True),
        sa.Column("reference", sa.String(length=255), nullable=True),
        sa.Column("notes", sa.String(length=512), nullable=True),
        sa.Column("raw", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        *_timestamps(),
        sa.ForeignKeyConstraint(
            ["order_id"],
            ["orders.id"],
            name=op.f("fk_transactions_order_id_orders"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_transactions")),
    )
    op.create_index(op.f("ix_transactions_order_id"), "transactions", ["order_id"])
    op.create_index(op.f("ix_transactions_type"), "transactions", ["type"])
    op.create_index(op.f("ix_transactions_provider"), "transactions", ["provider"])

    # --- wallet_balances -----------------------------------------------------
    op.create_table(
        "wallet_balances",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("currency", sa.String(length=3), nullable=False),
        sa.Column(
            "balance",
            sa.Numeric(precision=14, scale=2),
            nullable=False,
            server_default="0",
        ),
        *_timestamps(),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_wallet_balances")),
        sa.UniqueConstraint(
            "provider", "currency", name="uq_wallet_balances_provider_currency"
        ),
    )
    op.create_index(
        op.f("ix_wallet_balances_provider"), "wallet_balances", ["provider"]
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_wallet_balances_provider"), table_name="wallet_balances")
    op.drop_table("wallet_balances")

    op.drop_index(op.f("ix_transactions_provider"), table_name="transactions")
    op.drop_index(op.f("ix_transactions_type"), table_name="transactions")
    op.drop_index(op.f("ix_transactions_order_id"), table_name="transactions")
    op.drop_table("transactions")

    op.drop_index(op.f("ix_orders_status"), table_name="orders")
    op.drop_index(op.f("ix_orders_inventory_id"), table_name="orders")
    op.drop_index(op.f("ix_orders_product_id"), table_name="orders")
    op.drop_index(op.f("ix_orders_marketplace_sku"), table_name="orders")
    op.drop_index(op.f("ix_orders_external_order_id"), table_name="orders")
    op.drop_index(op.f("ix_orders_provider"), table_name="orders")
    op.drop_table("orders")

    op.drop_index(op.f("ix_inventory_batch_id"), table_name="inventory")
    op.drop_index(op.f("ix_inventory_reserved_order_id"), table_name="inventory")
    op.drop_index(op.f("ix_inventory_status"), table_name="inventory")
    op.drop_index(op.f("ix_inventory_product_id"), table_name="inventory")
    op.drop_table("inventory")
