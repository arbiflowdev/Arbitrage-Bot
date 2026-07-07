"""per-unit order items (multi-quantity fulfillment)

Revision ID: 0006_order_items
Revises: 0005_alerts
Create Date: 2026-07-07 00:00:00

Adds ``order_items`` — one row per ordered unit — so an order for quantity N is
fulfilled and delivered unit by unit instead of delivering a single code and
marking the whole order done. No backfill is needed: the fulfillment service
lazily creates the rows for any pre-existing order the first time it runs.
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa

from alembic import op

revision: str = "0006_order_items"
down_revision: str | None = "0005_alerts"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "order_items",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("order_id", sa.BigInteger(), nullable=False),
        sa.Column("unit_index", sa.Integer(), nullable=False, server_default="0"),
        sa.Column(
            "status", sa.String(length=16), nullable=False, server_default="pending"
        ),
        sa.Column("inventory_id", sa.BigInteger(), nullable=True),
        sa.Column("fulfillment_source", sa.String(length=16), nullable=True),
        sa.Column("delivery_reference", sa.String(length=255), nullable=True),
        sa.Column("delivered_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_error", sa.String(length=1024), nullable=True),
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
            ["order_id"],
            ["orders.id"],
            name=op.f("fk_order_items_order_id_orders"),
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["inventory_id"],
            ["inventory.id"],
            name=op.f("fk_order_items_inventory_id_inventory"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_order_items")),
        sa.UniqueConstraint(
            "order_id", "unit_index", name="uq_order_items_order_unit"
        ),
    )
    op.create_index(op.f("ix_order_items_order_id"), "order_items", ["order_id"])
    op.create_index(op.f("ix_order_items_status"), "order_items", ["status"])
    op.create_index(
        op.f("ix_order_items_inventory_id"), "order_items", ["inventory_id"]
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_order_items_inventory_id"), table_name="order_items")
    op.drop_index(op.f("ix_order_items_status"), table_name="order_items")
    op.drop_index(op.f("ix_order_items_order_id"), table_name="order_items")
    op.drop_table("order_items")
