"""Manual inventory — deliverable codes/keys we hold in stock.

Each row is one digital deliverable (a game key, code, etc.). The fulfillment
pipeline claims an AVAILABLE row, reserves it to an order, then marks it SOLD on
successful delivery. ``code`` is sensitive and is never logged; the API masks it
by default.

``reserved_order_id`` is a *soft* reference to ``orders.id`` (not a hard FK) so
the inventory and orders tables have no circular foreign-key dependency.
"""

from __future__ import annotations

import enum
from datetime import datetime

from sqlalchemy import (
    DateTime,
    Enum,
    ForeignKey,
    Numeric,
    String,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import JSONB, PK_TYPE, Base, TimestampedMixin


class InventoryStatus(str, enum.Enum):
    AVAILABLE = "available"
    RESERVED = "reserved"
    SOLD = "sold"
    INVALID = "invalid"


class Inventory(TimestampedMixin, Base):
    __tablename__ = "inventory"

    product_id: Mapped[int | None] = mapped_column(
        PK_TYPE,
        ForeignKey("products.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    code: Mapped[str] = mapped_column(String(512), nullable=False)
    status: Mapped[InventoryStatus] = mapped_column(
        Enum(InventoryStatus, name="inventory_status", native_enum=False, length=16),
        nullable=False,
        default=InventoryStatus.AVAILABLE,
        server_default=InventoryStatus.AVAILABLE.value,
        index=True,
    )
    region: Mapped[str | None] = mapped_column(String(64), nullable=True)
    platform: Mapped[str | None] = mapped_column(String(64), nullable=True)
    source_cost: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    currency: Mapped[str | None] = mapped_column(String(3), nullable=True)
    reserved_order_id: Mapped[int | None] = mapped_column(
        PK_TYPE, nullable=True, index=True
    )
    reserved_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    sold_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    batch_id: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    notes: Mapped[str | None] = mapped_column(String(512), nullable=True)
    raw: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
