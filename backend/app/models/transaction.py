"""Money + delivery ledger.

A signed audit trail of every financial movement: sale revenue (credit),
just-in-time purchases (debit), fees, manual adjustments, and wallet top-ups.
``amount`` is signed (credit positive, debit negative) so a simple SUM gives the
net position. ``balance_after`` captures the wallet balance immediately after
the movement for point-in-time auditing.
"""

from __future__ import annotations

import enum

from sqlalchemy import Enum, ForeignKey, Numeric, String
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import JSONB, PK_TYPE, Base, TimestampedMixin


class TransactionType(str, enum.Enum):
    SALE_REVENUE = "sale_revenue"  # credit: a delivered order
    JIT_PURCHASE = "jit_purchase"  # debit: bought stock to fulfill an order
    FEE = "fee"  # debit: marketplace/withdrawal fee
    ADJUSTMENT = "adjustment"  # manual correction
    TOP_UP = "top_up"  # credit: operator added funds


class Transaction(TimestampedMixin, Base):
    __tablename__ = "transactions"

    order_id: Mapped[int | None] = mapped_column(
        PK_TYPE,
        ForeignKey("orders.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    type: Mapped[TransactionType] = mapped_column(
        Enum(TransactionType, name="transaction_type", native_enum=False, length=16),
        nullable=False,
        index=True,
    )
    provider: Mapped[str | None] = mapped_column(String(64), nullable=True, index=True)
    amount: Mapped[float] = mapped_column(Numeric(14, 2), nullable=False)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    balance_after: Mapped[float | None] = mapped_column(Numeric(14, 2), nullable=True)
    reference: Mapped[str | None] = mapped_column(String(255), nullable=True)
    notes: Mapped[str | None] = mapped_column(String(512), nullable=True)
    raw: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
