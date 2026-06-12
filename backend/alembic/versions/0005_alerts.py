"""alerts table

Revision ID: 0005_alerts
Revises: 0004_fulfillment
Create Date: 2026-06-08 00:00:00
"""

from __future__ import annotations

from collections.abc import Sequence

import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

from alembic import op

revision: str = "0005_alerts"
down_revision: str | None = "0004_fulfillment"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "alerts",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("type", sa.String(length=20), nullable=False),
        sa.Column("severity", sa.String(length=10), nullable=False),
        sa.Column("status", sa.String(length=12), nullable=False, server_default="open"),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("message", sa.String(length=2000), nullable=False),
        sa.Column("dedupe_key", sa.String(length=128), nullable=True),
        sa.Column("provider", sa.String(length=64), nullable=True),
        sa.Column("order_id", sa.BigInteger(), nullable=True),
        sa.Column("context", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("acknowledged_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("resolved_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column(
            "created_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.func.now(),
        ),
        sa.Column(
            "updated_at", sa.DateTime(timezone=True), nullable=False,
            server_default=sa.func.now(),
        ),
        sa.ForeignKeyConstraint(
            ["order_id"], ["orders.id"],
            name=op.f("fk_alerts_order_id_orders"), ondelete="SET NULL",
        ),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_alerts")),
    )
    op.create_index(op.f("ix_alerts_type"), "alerts", ["type"])
    op.create_index(op.f("ix_alerts_status"), "alerts", ["status"])
    op.create_index(op.f("ix_alerts_dedupe_key"), "alerts", ["dedupe_key"])
    op.create_index(op.f("ix_alerts_order_id"), "alerts", ["order_id"])


def downgrade() -> None:
    op.drop_index(op.f("ix_alerts_order_id"), table_name="alerts")
    op.drop_index(op.f("ix_alerts_dedupe_key"), table_name="alerts")
    op.drop_index(op.f("ix_alerts_status"), table_name="alerts")
    op.drop_index(op.f("ix_alerts_type"), table_name="alerts")
    op.drop_table("alerts")
