"""Our own listing of a product on a marketplace.

A Listing represents a sell-side offer we publish to a provider (Kinguin, G2G).
It tracks the desired price/stock and the synchronisation state with the remote
marketplace so operators can see what is live and what failed to push.
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


class ListingStatus(str, enum.Enum):
    DRAFT = "draft"  # created locally, not yet pushed
    ACTIVE = "active"  # live on the marketplace
    INACTIVE = "inactive"  # delisted / paused
    SYNCED = "synced"  # last push to the marketplace succeeded
    ERROR = "error"  # last sync attempt failed (see sync_error)
    REMOVED = "removed"  # remote offer no longer exists (404/410); auto-retired


class Listing(TimestampedMixin, Base):
    __tablename__ = "listings"
    __table_args__ = (
        UniqueConstraint(
            "provider", "marketplace_sku", name="uq_listings_provider_sku"
        ),
    )

    provider: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    marketplace_sku: Mapped[str] = mapped_column(
        String(128), nullable=False, index=True
    )
    external_listing_id: Mapped[str | None] = mapped_column(
        String(128), nullable=True, index=True
    )
    product_id: Mapped[int | None] = mapped_column(
        PK_TYPE,
        ForeignKey("products.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    title: Mapped[str | None] = mapped_column(String(255), nullable=True)
    price: Mapped[float | None] = mapped_column(Numeric(12, 2), nullable=True)
    currency: Mapped[str | None] = mapped_column(String(3), nullable=True)
    stock: Mapped[int] = mapped_column(
        Integer, nullable=False, default=0, server_default="0"
    )
    status: Mapped[ListingStatus] = mapped_column(
        Enum(ListingStatus, name="listing_status", native_enum=False, length=16),
        nullable=False,
        default=ListingStatus.DRAFT,
        server_default=ListingStatus.DRAFT.value,
        index=True,
    )
    last_synced_at: Mapped[datetime | None] = mapped_column(
        DateTime(timezone=True), nullable=True
    )
    sync_error: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    raw: Mapped[dict | None] = mapped_column(JSONB, nullable=True)
