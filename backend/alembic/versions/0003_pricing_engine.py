"""arbitrage & dynamic pricing engine

Revision ID: 0003_pricing_engine
Revises: 0002_marketplace_integrations
Create Date: 2026-06-03 00:00:00

Milestone-3 schema:
    * pricing_snapshots   - cached competitor landscape per scan
    * repricing_history   - audit trail of every repricing decision
    * fee_structures      - per-provider/category composite-fee overrides
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0003_pricing_engine"
down_revision: str | None = "0002_marketplace_integrations"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # --- pricing_snapshots ---------------------------------------------------
    op.create_table(
        "pricing_snapshots",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("marketplace_sku", sa.String(length=128), nullable=False),
        sa.Column("product_id", sa.BigInteger(), nullable=True),
        sa.Column(
            "base_currency", sa.String(length=3), nullable=False, server_default="EUR"
        ),
        sa.Column("lowest_price", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column("second_price", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column("third_price", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column("source_cost", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column(
            "competitor_count", sa.Integer(), nullable=False, server_default="0"
        ),
        sa.Column("competitors", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
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
            name=op.f("fk_pricing_snapshots_product_id_products"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_pricing_snapshots")),
    )
    op.create_index(
        op.f("ix_pricing_snapshots_provider"), "pricing_snapshots", ["provider"]
    )
    op.create_index(
        op.f("ix_pricing_snapshots_marketplace_sku"),
        "pricing_snapshots",
        ["marketplace_sku"],
    )
    op.create_index(
        op.f("ix_pricing_snapshots_product_id"), "pricing_snapshots", ["product_id"]
    )

    # --- repricing_history ---------------------------------------------------
    op.create_table(
        "repricing_history",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("marketplace_sku", sa.String(length=128), nullable=False),
        sa.Column("product_id", sa.BigInteger(), nullable=True),
        sa.Column("listing_id", sa.BigInteger(), nullable=True),
        sa.Column("strategy", sa.String(length=32), nullable=False),
        sa.Column(
            "currency", sa.String(length=3), nullable=False, server_default="EUR"
        ),
        sa.Column("old_price", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column("new_price", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("net_profit", sa.Numeric(precision=12, scale=2), nullable=False),
        sa.Column("margin", sa.Numeric(precision=7, scale=4), nullable=True),
        sa.Column("source_cost", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column("sales_fee", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column("withdrawal_fee", sa.Numeric(precision=12, scale=2), nullable=True),
        sa.Column(
            "competitor_reference", sa.Numeric(precision=12, scale=2), nullable=True
        ),
        sa.Column(
            "anomaly_detected",
            sa.Boolean(),
            nullable=False,
            server_default=sa.text("false"),
        ),
        sa.Column(
            "changed", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
        sa.Column(
            "applied", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
        sa.Column(
            "dry_run", sa.Boolean(), nullable=False, server_default=sa.text("false")
        ),
        sa.Column("error", sa.String(length=1024), nullable=True),
        sa.Column("notes", sa.String(length=512), nullable=True),
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
            name=op.f("fk_repricing_history_product_id_products"),
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["listing_id"],
            ["listings.id"],
            name=op.f("fk_repricing_history_listing_id_listings"),
            ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_repricing_history")),
    )
    op.create_index(
        op.f("ix_repricing_history_provider"), "repricing_history", ["provider"]
    )
    op.create_index(
        op.f("ix_repricing_history_marketplace_sku"),
        "repricing_history",
        ["marketplace_sku"],
    )
    op.create_index(
        op.f("ix_repricing_history_product_id"), "repricing_history", ["product_id"]
    )
    op.create_index(
        op.f("ix_repricing_history_listing_id"), "repricing_history", ["listing_id"]
    )
    op.create_index(
        op.f("ix_repricing_history_strategy"), "repricing_history", ["strategy"]
    )

    # --- fee_structures ------------------------------------------------------
    op.create_table(
        "fee_structures",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("provider", sa.String(length=64), nullable=False),
        sa.Column("category", sa.String(length=128), nullable=True),
        sa.Column(
            "sales_percent",
            sa.Numeric(precision=7, scale=4),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "sales_fixed",
            sa.Numeric(precision=12, scale=2),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "withdrawal_percent",
            sa.Numeric(precision=7, scale=4),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "withdrawal_fixed",
            sa.Numeric(precision=12, scale=2),
            nullable=False,
            server_default="0",
        ),
        sa.Column(
            "is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")
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
        sa.PrimaryKeyConstraint("id", name=op.f("pk_fee_structures")),
        sa.UniqueConstraint(
            "provider", "category", name="uq_fee_structures_provider_category"
        ),
    )
    op.create_index(
        op.f("ix_fee_structures_provider"), "fee_structures", ["provider"]
    )


def downgrade() -> None:
    op.drop_index(op.f("ix_fee_structures_provider"), table_name="fee_structures")
    op.drop_table("fee_structures")

    op.drop_index(
        op.f("ix_repricing_history_strategy"), table_name="repricing_history"
    )
    op.drop_index(
        op.f("ix_repricing_history_listing_id"), table_name="repricing_history"
    )
    op.drop_index(
        op.f("ix_repricing_history_product_id"), table_name="repricing_history"
    )
    op.drop_index(
        op.f("ix_repricing_history_marketplace_sku"), table_name="repricing_history"
    )
    op.drop_index(
        op.f("ix_repricing_history_provider"), table_name="repricing_history"
    )
    op.drop_table("repricing_history")

    op.drop_index(
        op.f("ix_pricing_snapshots_product_id"), table_name="pricing_snapshots"
    )
    op.drop_index(
        op.f("ix_pricing_snapshots_marketplace_sku"), table_name="pricing_snapshots"
    )
    op.drop_index(
        op.f("ix_pricing_snapshots_provider"), table_name="pricing_snapshots"
    )
    op.drop_table("pricing_snapshots")
