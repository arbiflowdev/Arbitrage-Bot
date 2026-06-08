"""A customer sale we must fulfill.

Orders arrive from a marketplace (via webhook or the polling safety net) and are
deduplicated on ``(provider, external_order_id)``. The fulfillment pipeline
moves an order RECEIVED -> PROCESSING -> DELIVERED (or AWAITING_STOCK / FAILED),
recording which inventory row satisfied it and whether it came from our own
stock (MANUAL) or a just-in-time purchase (JIT).
"""

from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import (
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import JSONB, PK_TYPE, Base, TimestampedMixin


class OrderStatus(str, enum.Enum):
    RECEIVED = "received"  # ingested, not yet fulfilled
    PROCESSING = "processing"  # fulfillment in progress
    AWAITING_STOCK = "awaiting_stock"  # no stock + JIT unavailable; will retry
    DELIVERED = "delivered"  # code delivered to the buyer
    FAILED = "failed"  # gave up after max attempts
    CANCELLED = "cancelled"  # cancelled upstream


class FulfillmentSource(str, enum.Enum):
    MANUAL = "manual"  # delivered from our own inventory
    JIT = "jit"  # sourced just-in-time from another marketplace


class Order(TimestampedMixin, Base):
    __tablename__ = "orders"
    __table_args__ = (
        UniqueConstraint(
            "provider", "external_order_id", name="uq_orders_provider_external_id"
        ),
    )

    provider: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    external_order_id: Mapped[str] = mapped_column(
        String(128), nullable=False, index=True
    )
    marketplace_sku: Mapped[str] = mapped_column(
        String(128), nullable=False, index=True
    )
    product_id: Mapped[int | None] = mapped_column(
        PK_TYPE,
        ForeignKey("products.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    quantity: Mapped[int] = mapped_column(
        Integer, nullable=False, default=1, server_default="1"
    )
    total: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    currency: Mapped[str | None] = mapped_column(String(3), nullable=True)
    status: Mapped[OrderStatus] = mapped_column(
        Enum(OrderStatus, name="order_status", native_enum=False, length=20),
        nullable=False,
        default=OrderStatus.RECEIVED,
        server_default=OrderStatus.RECEIVED.value,
        index=True,
    )
    fulfillment_source: Mapped[FulfillmentSource | None] = mapped_column(
        Enum(
            FulfillmentSource,
            name="fulfillment_source",
            native_enum=False,
            length=16,
        ),
        nullable=True,
    )
    inventory_id: Mapped[int | None] = mapped_column(
        PK_TYPE,
        ForeignKey("inventory.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    attempts: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    last_error: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    received_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    delivered_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    raw: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
