"""SKU mapping that links an internal product to a marketplace-specific id.

One row per (product, marketplace) pair
"""

from __future__ import annotations

from sqlalchemy import ForeignKey, String, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from app.models.base import JSONB, PK_TYPE, Base, TimestampedMixin
from app.models.product import Product


class SkuMapping(TimestampedMixin, Base):
    __tablename__ = "sku_mappings"
    __table_args__ = (
        UniqueConstraint(
            "marketplace", "marketplace_sku", name="uq_sku_mappings_marketplace_sku"
        ),
    )

    product_id: Mapped[int] = mapped_column(
        PK_TYPE,
        ForeignKey("products.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    marketplace: Mapped[str] = mapped_column(String(64), nullable=False, index=True)
    marketplace_sku: Mapped[str] = mapped_column(String(128), nullable=False)
    marketplace_url: Mapped[str | None] = mapped_column(String(1024), nullable=True)
    extra: Mapped[dict | None] = mapped_column(JSONB, nullable=True)

    product: Mapped[Product] = relationship(Product, lazy="selectin")
