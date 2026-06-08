"""Order intake — turn a marketplace order into a fulfillable ``orders`` row.

Idempotent on ``(provider, external_order_id)`` so the same sale arriving twice
(webhook + polling safety net, or a provider replay) is never fulfilled twice.
The product is resolved from the marketplace SKU via ``sku_mappings``.
"""

from __future__ import annotations

from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.logging import get_logger
from app.integrations.base import NormalizedOrder
from app.models.order import Order, OrderStatus
from app.repositories.order_repository import OrderRepository
from app.repositories.sku_mapping_repository import SkuMappingRepository
from app.utils.datetime import utcnow

log = get_logger(__name__)


class OrderIntakeService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.repo = OrderRepository(session)
        self.mappings = SkuMappingRepository(session)

    async def ingest(
        self,
        provider: str,
        external_order_id: str,
        marketplace_sku: str,
        *,
        quantity: int = 1,
        total: Decimal | None = None,
        currency: str | None = None,
        raw: dict | None = None,
    ) -> tuple[Order, bool]:
        """Create (or return existing) order. Returns ``(order, created)``."""
        existing = await self.repo.get_by_external(provider, external_order_id)
        if existing is not None:
            log.info(
                "fulfillment.order_duplicate",
                provider=provider,
                external_order_id=external_order_id,
            )
            return existing, False

        mapping = await self.mappings.get_by_marketplace_sku(provider, marketplace_sku)
        order = Order(
            provider=provider,
            external_order_id=external_order_id,
            marketplace_sku=marketplace_sku,
            product_id=mapping.product_id if mapping else None,
            quantity=quantity,
            total=total,
            currency=currency,
            status=OrderStatus.RECEIVED,
            received_at=utcnow(),
            raw=raw,
        )
        await self.repo.add(order)
        log.info(
            "fulfillment.order_received",
            provider=provider,
            external_order_id=external_order_id,
            product_id=order.product_id,
        )
        return order, True

    async def ingest_normalized(
        self, provider: str, order: NormalizedOrder
    ) -> tuple[Order, bool]:
        return await self.ingest(
            provider,
            order.external_order_id,
            order.marketplace_sku,
            quantity=order.quantity,
            total=order.total,
            currency=order.currency,
            raw=order.raw,
        )
