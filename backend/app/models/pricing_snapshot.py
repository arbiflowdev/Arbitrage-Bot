"""Cached competitor-price snapshot captured during a pricing scan.

One row per ``(provider, marketplace_sku)`` per scan records the competitor
landscape (already converted to the base currency) that a repricing decision
was based on. These snapshots back the "cached pricing snapshots" deliverable
and let operators audit *why* a price was set.
"""

from __future__ import annotations

from sqlalchemy import ForeignKey, Integer, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import JSONB, PK_TYPE, Base, TimestampedMixin


class PricingSnapshot(TimestampedMixin, Base):
    __tablename__ = "pricing_snapshots"

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
    base_currency: Mapped[str] = mapped_column(
        String(3), nullable=False, default="EUR"
    )
    lowest_price: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    second_price: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    third_price: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    source_cost: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    competitor_count: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    # Full sorted competitor list (base currency) + any extra context.
    competitors: Mapped[list | None] = mapped_column(JSONB, nullable=True)
    raw: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
