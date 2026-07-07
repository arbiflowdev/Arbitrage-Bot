"""A single deliverable unit of an order.

An order for ``quantity`` units expands into ``quantity`` ``order_items`` rows,
one per code the buyer paid for. Each unit is fulfilled independently — reserved
from our own inventory (or sourced just-in-time) and delivered on its own — so a
multi-quantity order can be partially delivered (some units DELIVERED while the
rest wait for stock) and the parent order is only marked DELIVERED once every
unit is. This is what lets the bot honour a qty>1 sale instead of delivering a
single code and stranding the rest.
"""

from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import (
    DateTime,
    Enum,
    ForeignKey,
    Integer,
    String,
    UniqueConstraint,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import PK_TYPE, Base, TimestampedMixin
from app.models.order import FulfillmentSource


class OrderItemStatus(str, enum.Enum):
    PENDING = "pending"  # not yet delivered
    DELIVERED = "delivered"  # code delivered to the buyer


class OrderItem(TimestampedMixin, Base):
    __tablename__ = "order_items"
    __table_args__ = (
        UniqueConstraint("order_id", "unit_index", name="uq_order_items_order_unit"),
    )

    order_id: Mapped[int] = mapped_column(
        PK_TYPE,
        ForeignKey("orders.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    #: 0-based position of this unit within its order (0 .. quantity-1).
    unit_index: Mapped[int] = mapped_column(Integer, nullable=False, default=0)
    status: Mapped[OrderItemStatus] = mapped_column(
        Enum(OrderItemStatus, name="order_item_status", native_enum=False, length=16),
        nullable=False,
        default=OrderItemStatus.PENDING,
        server_default=OrderItemStatus.PENDING.value,
        index=True,
    )
    inventory_id: Mapped[int | None] = mapped_column(
        PK_TYPE,
        ForeignKey("inventory.id", ondelete="SET NULL"),
        nullable=True,
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
    delivery_reference: Mapped[str | None] = mapped_column(String(255), nullable=True)
    delivered_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    last_error: Mapped[str | None] = mapped_column(String(1024), nullable=True)
