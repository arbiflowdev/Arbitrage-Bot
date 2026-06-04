"""Audit trail of every repricing decision the engine makes.

One row per decision, whether or not the price actually changed and whether or
not it was pushed live (dry-run records the decision without pushing). This is
the "repricing history tracking" deliverable and the source for historical
pricing logs.
"""

from __future__ import annotations

from sqlalchemy import Boolean, ForeignKey, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import PK_TYPE, Base, TimestampedMixin


class RepricingHistory(TimestampedMixin, Base):
    __tablename__ = "repricing_history"

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
    listing_id: Mapped[int | None] = mapped_column(
        PK_TYPE,
        ForeignKey("listings.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    strategy: Mapped[str] = mapped_column(String(32), nullable=False, index=True)
    currency: Mapped[str] = mapped_column(String(3), nullable=False, default="EUR")
    old_price: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    new_price: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    net_profit: Mapped[float] = mapped_column(Numeric(12, 2), nullable=False)
    margin: Mapped[float | None] = mapped_column(Numeric(7, 4), nullable=True)
    source_cost: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    sales_fee: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    withdrawal_fee: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    competitor_reference: Mapped[float | None] = mapped_column(
        Numeric(12, 2), nullable=True
    )
    anomaly_detected: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    changed: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    applied: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    dry_run: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=False, server_default="false"
    )
    error: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    notes: Mapped[str | None] = mapped_column(String(512), nullable=True)
