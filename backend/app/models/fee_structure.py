"""Per-provider (and optional per-category) composite fee override.

The platform-wide / category fee "tier table" the client asked for. When a row
exists for a provider (and optionally a category) it overrides the ``.env``
fee defaults; otherwise the engine falls back to settings. Percentages are
stored as human-readable percents (e.g. ``11.000`` for 11%).
"""

from __future__ import annotations

from sqlalchemy import Boolean, Numeric, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column

from app.models.base import Base, TimestampedMixin


class FeeStructure(TimestampedMixin, Base):
    __tablename__ = "fee_structures"
    __table_args__ = (
        UniqueConstraint(
            "provider", "category", name="uq_fee_structures_provider_category"
        ),
    )

    provider: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    # NULL category == platform-wide default for the provider.
    category: Mapped[str | None] = mapped_column(String(128), nullable=True)
    sales_percent: Mapped[float] = mapped_column(
        Numeric(7, 4), nullable=False, default=0, server_default="0"
    )
    sales_fixed: Mapped[float] = mapped_column(
        Numeric(12, 2), nullable=False, default=0, server_default="0"
    )
    withdrawal_percent: Mapped[float] = mapped_column(
        Numeric(7, 4), nullable=False, default=0, server_default="0"
    )
    withdrawal_fixed: Mapped[float] = mapped_column(
        Numeric(12, 2), nullable=False, default=0, server_default="0"
    )
    is_active: Mapped[bool] = mapped_column(
        Boolean, nullable=False, default=True, server_default="true"
    )
