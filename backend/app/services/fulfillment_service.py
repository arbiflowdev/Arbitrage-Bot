"""Hybrid order fulfillment orchestrator.

For each order: deliver from our own manual inventory first; if we are out of
stock, source the code just-in-time from the cheapest other marketplace; then
deliver it to the buyer. The whole operation is transaction-safe and idempotent:

- A Redis per-order lock (best-effort) plus a row-locked re-read serialise
  concurrent attempts across workers/instances.
- An already-``DELIVERED`` order short-circuits, so a code is never delivered
  twice (the core duplicate-prevention guarantee).
- On any failure the inventory reservation is released and the order is left in
  a retryable state (or ``AWAITING_STOCK`` when nothing can satisfy it yet).
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.core.redis import acquire_lock, enqueue
from app.fulfillment.exceptions import InsufficientFunds, SourcingUnavailable
from app.integrations import build_adapter, resolve_credentials
from app.integrations.base import DeliveryResult
from app.models.alert import AlertSeverity, AlertType
from app.models.inventory import Inventory
from app.models.log import LogLevel
from app.models.order import FulfillmentSource, Order, OrderStatus
from app.models.transaction import TransactionType
from app.repositories.order_repository import OrderRepository
from app.services.alert_service import AlertService
from app.services.currency_service import CurrencyService
from app.services.event_log_service import record_event
from app.services.inventory_service import InventoryService
from app.services.sourcing_service import SourcingService
from app.services.wallet_service import WalletService
from app.utils.datetime import utcnow

log = get_logger(__name__)

FULFILLMENT_QUEUE = "fulfillment"


@dataclass(slots=True)
class FulfillResult:
    order_id: int
    delivered: bool
    status: str | None
    source: str | None = None
    error: str | None = None


class FulfillmentService:
    def __init__(
        self, session: AsyncSession, *, currency: CurrencyService | None = None
    ) -> None:
        self.session = session
        self.currency = currency or CurrencyService()
        self.orders = OrderRepository(session)
        self.inventory = InventoryService(session)
        self.wallet = WalletService(session)
        self.alerts = AlertService(session)
        self.sourcing = SourcingService(
            session, currency=self.currency, wallet=self.wallet
        )

    async def fulfill(self, order_id: int) -> FulfillResult:
        order = await self.orders.get_by_id(order_id)
        if order is None:
            return FulfillResult(order_id, False, None, error="order not found")

        lock = await self._acquire_lock(order)
        try:
            order = await self.orders.get_for_update(order_id) or order

            # Idempotency: never deliver an order that is already done.
            if order.status is OrderStatus.DELIVERED:
                return FulfillResult(
                    order.id, False, order.status.value, error="already delivered"
                )

            order.attempts += 1
            order.status = OrderStatus.PROCESSING

            if order.product_id is None:
                return await self._fail(order, "no product mapped for order")

            inventory, source = await self._obtain_stock(order)
            if inventory is None:
                # _obtain_stock has already set AWAITING_STOCK + committed.
                return FulfillResult(
                    order.id,
                    False,
                    order.status.value,
                    error=order.last_error,
                )

            return await self._deliver_and_settle(order, inventory, source)
        except Exception as exc:  # noqa: BLE001 — never crash the worker loop
            await self.session.rollback()
            log.warning(
                "fulfillment.unexpected_error", order_id=order_id, error=str(exc)
            )
            return FulfillResult(order_id, False, None, error=str(exc))
        finally:
            await self._release_lock(lock)

    # ---- stock acquisition (inventory-first, then JIT) --------------------
    async def _obtain_stock(
        self, order: Order
    ) -> tuple[Inventory | None, FulfillmentSource | None]:
        item = await self.inventory.reserve_one(order.product_id, order.id)
        if item is not None:
            return item, FulfillmentSource.MANUAL

        if not settings.JIT_ENABLED:
            await self._await_stock(order, "out of stock; JIT disabled")
            return None, None

        try:
            result = await self.sourcing.source(
                order.product_id, order.provider, order.id
            )
            return result.inventory, FulfillmentSource.JIT
        except (SourcingUnavailable, InsufficientFunds) as exc:
            await self._await_stock(order, str(exc))
            return None, None

    # ---- delivery + settlement -------------------------------------------
    async def _deliver_and_settle(
        self, order: Order, inventory: Inventory, source: FulfillmentSource | None
    ) -> FulfillResult:
        try:
            delivery = await self._deliver(order, inventory.code)
        except Exception as exc:  # noqa: BLE001 — delivery is best-effort
            return await self._retry_or_fail(order, inventory, f"delivery error: {exc}")

        if not delivery.success:
            return await self._retry_or_fail(
                order, inventory, "delivery rejected by marketplace"
            )

        await self.inventory.mark_sold(inventory.id)
        order.status = OrderStatus.DELIVERED
        order.fulfillment_source = source
        order.inventory_id = inventory.id
        order.delivered_at = utcnow()
        order.last_error = None
        await self.alerts.resolve_by_dedupe(f"awaiting-{order.id}")
        await record_event(
            self.session,
            LogLevel.INFO,
            "fulfillment",
            f"Order {order.id} delivered via {source.value if source else 'n/a'}",
            {"order_id": order.id, "provider": order.provider},
        )

        if order.total is not None:
            await self.wallet.credit(
                order.provider,
                order.currency or settings.BASE_CURRENCY,
                Decimal(order.total),
                order_id=order.id,
                type=TransactionType.SALE_REVENUE,
                reference=delivery.reference,
            )

        await self.session.commit()
        log.info(
            "fulfillment.delivered",
            order_id=order.id,
            source=source.value if source else None,
        )
        return FulfillResult(
            order.id,
            True,
            order.status.value,
            source=source.value if source else None,
        )

    async def _deliver(self, order: Order, code: str) -> DeliveryResult:
        adapter = build_adapter(order.provider, resolve_credentials(order.provider))
        try:
            return await adapter.deliver(
                order.external_order_id, code, marketplace_sku=order.marketplace_sku
            )
        finally:
            await adapter.aclose()

    # ---- failure handling -------------------------------------------------
    async def _await_stock(self, order: Order, message: str) -> None:
        order.status = OrderStatus.AWAITING_STOCK
        order.last_error = message[:1024]
        await self.alerts.raise_alert(
            AlertType.AWAITING_STOCK,
            AlertSeverity.WARNING,
            f"Order {order.id} awaiting stock",
            message,
            dedupe_key=f"awaiting-{order.id}",
            provider=order.provider,
            order_id=order.id,
        )
        await record_event(
            self.session,
            LogLevel.WARNING,
            "fulfillment",
            f"Order {order.id} awaiting stock: {message}",
            {"order_id": order.id, "provider": order.provider},
        )
        await self.session.commit()
        await self._enqueue_retry(order.id)
        log.info("fulfillment.awaiting_stock", order_id=order.id, reason=message)

    async def _retry_or_fail(
        self, order: Order, inventory: Inventory, message: str
    ) -> FulfillResult:
        await self.inventory.release(inventory.id)
        order.last_error = message[:1024]
        order.inventory_id = None
        if order.attempts >= settings.FULFILLMENT_MAX_ATTEMPTS:
            order.status = OrderStatus.FAILED
            await self.alerts.raise_alert(
                AlertType.ORDER_FAILED,
                AlertSeverity.CRITICAL,
                f"Order {order.id} failed",
                message,
                dedupe_key=f"order-failed-{order.id}",
                provider=order.provider,
                order_id=order.id,
            )
            await record_event(
                self.session,
                LogLevel.ERROR,
                "fulfillment",
                f"Order {order.id} failed after {order.attempts} attempts: {message}",
                {"order_id": order.id, "provider": order.provider},
            )
            retryable = False
        else:
            order.status = OrderStatus.RECEIVED
            retryable = True
        await self.session.commit()
        if retryable:
            await self._enqueue_retry(order.id)
        log.warning(
            "fulfillment.delivery_failed",
            order_id=order.id,
            attempts=order.attempts,
            retryable=retryable,
            error=message,
        )
        return FulfillResult(
            order.id, False, order.status.value, error=message
        )

    async def _fail(self, order: Order, message: str) -> FulfillResult:
        order.status = OrderStatus.FAILED
        order.last_error = message[:1024]
        await self.alerts.raise_alert(
            AlertType.ORDER_FAILED,
            AlertSeverity.CRITICAL,
            f"Order {order.id} failed",
            message,
            dedupe_key=f"order-failed-{order.id}",
            provider=order.provider,
            order_id=order.id,
        )
        await record_event(
            self.session,
            LogLevel.ERROR,
            "fulfillment",
            f"Order {order.id} failed: {message}",
            {"order_id": order.id, "provider": order.provider},
        )
        await self.session.commit()
        log.warning("fulfillment.failed", order_id=order.id, error=message)
        return FulfillResult(order.id, False, order.status.value, error=message)

    # ---- redis helpers (best-effort; safe when Redis is absent) -----------
    async def _acquire_lock(self, order: Order):  # noqa: ANN202
        if settings.APP_ENV == "test":
            return None  # tests rely on DB-level idempotency, not Redis
        try:
            lock = acquire_lock(
                f"fulfill:{order.provider}:{order.external_order_id}",
                timeout=120,
                blocking_timeout=0,
            )
            return lock if await lock.acquire() else None
        except Exception:  # noqa: BLE001 — Redis down: rely on DB-level guards
            return None

    async def _release_lock(self, lock) -> None:  # noqa: ANN001
        if lock is None:
            return
        try:
            await lock.release()
        except Exception:  # noqa: BLE001
            pass

    async def _enqueue_retry(self, order_id: int) -> None:
        if settings.APP_ENV == "test":
            return
        try:
            await enqueue(FULFILLMENT_QUEUE, str(order_id))
        except Exception:  # noqa: BLE001 — queue is a best-effort accelerator
            pass
