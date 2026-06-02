"""Latest known market price for a marketplace SKU.

One row per ``(provider, marketplace_sku)`` — refreshed (upserted) on every
price sync. Historical price snapshots are a Milestone-3 concern; this table
holds only the most recent observation used by the repricing engine later.
"""

from __future__ import annotations

from datetime import datetime

from sqlalchemy import (
    Boolean,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    String,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import JSONB, PK_TYPE, Base, TimestampedMixin


class MarketplacePrice(TimestampedMixin, Base):
    __tablename__ = "marketplace_prices"
    __table_args__ = (
        UniqueConstraint(
            "provider", "marketplace_sku", name="uq_marketplace_prices_provider_sku"
        ),
    )

    provider: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    marketplace_sku: Mapped[str] = mapped_column(
        String(128), nullable=False, index=True
    )
    product_id: Mapped[int | None] = mapped_column(
        PK_TYPE,
        ForeignKey("products.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="EUR")
    price: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    available_qty: Mapped[int | None] = mapped_column(Integer, nullable=True)
    is_available: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
    raw: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
    fetched_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
