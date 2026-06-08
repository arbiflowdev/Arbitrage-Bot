"""Per-marketplace wallet balance used to fund just-in-time purchases.

One row per ``(provider, currency)``. The balance is mutated under a row lock
(``SELECT ... FOR UPDATE``) so concurrent fulfillment workers can never double
-spend. Top-ups credit it; JIT purchases debit it (and are rejected if funds are
insufficient when enforcement is on).
"""

from __future__ import annotations

from sqlalchemy import Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampedMixin


class WalletBalance(TimestampedMixin, Base):
    __tablename__ = "wallet_balances"
    __table_args__ = (
        UniqueConstraint(
            "provider", "currency", name="uq_wallet_balances_provider_currency"
        ),
    )

    provider: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    currency: Mapped[str] = mapped_column(String(3), nullable=False)
    balance: Mapped[float] = mapped_column(
        Numeric(14, 2), nullable=False, default=0, server_default="0"
    )
