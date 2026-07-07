"""Hybrid order fulfillment orchestrator.

An order for ``quantity`` units is fulfilled unit by unit (each tracked by an
``order_items`` row). For each undelivered unit: deliver from our own manual
inventory first; if we are out of stock, source the code just-in-time from the
cheapest other marketplace; then deliver it to the buyer. The parent order is
only marked ``DELIVERED`` once every unit is — a multi-quantity sale can be
partially delivered and finished on a later retry. The whole operation is
transaction-safe and idempotent:

- A Redis per-order lock (best-effort) plus a row-locked re-read serialise
  concurrent attempts across workers/instances.
- An already-``DELIVERED`` order short-circuits, and each already-delivered unit
  is skipped, so a code is never delivered twice (the core duplicate-prevention
  guarantee).
- On any per-unit failure that unit's inventory reservation is released and the
  order is left in a retryable state (or ``AWAITING_STOCK`` when nothing can
  satisfy the remaining units yet).
"""

from __future__ import annotations

import enum
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
from app.models.order_item import OrderItem, OrderItemStatus
from app.models.transaction import TransactionType
from app.repositories.order_item_repository import OrderItemRepository
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


class _UnitOutcome(enum.Enum):
    """Why a single unit's fulfillment attempt ended."""

    DELIVERED = "delivered"
    NO_STOCK = "no_stock"  # out of stock and JIT could not source it
    DELIVERY_FAILED = "delivery_failed"  # a code was obtained but delivery failed


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
        self.items = OrderItemRepository(session)
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

            # Idempotency: never re-process an order that is already done.
            if order.status is OrderStatus.DELIVERED:
                return FulfillResult(
                    order.id, False, order.status.value, error="already delivered"
                )

            order.attempts += 1
            order.status = OrderStatus.PROCESSING

            if order.product_id is None:
                return await self._fail(order, "no product mapped for order")

            # Fan the order out into one row per ordered unit, then deliver each
            # undelivered unit independently.
            items = await self._ensure_items(order)
            pending = [
                i for i in items if i.status is not OrderItemStatus.DELIVERED
            ]
            blocking: _UnitOutcome | None = None
            for item in pending:
                outcome = await self._deliver_unit(order, item)
                if outcome is not _UnitOutcome.DELIVERED:
                    # Stop at the first unit we cannot fill this pass; the sweep
                    # will retry the rest once restocked / the failure clears.
                    blocking = outcome
                    break

            return await self._finalize(order, items, blocking)
        except Exception as exc:  # noqa: BLE001 — never crash the worker loop
            await self.session.rollback()
            log.warning(
                "fulfillment.unexpected_error", order_id=order_id, error=str(exc)
            )
            return FulfillResult(order_id, False, None, error=str(exc))
        finally:
            await self._release_lock(lock)

    async def _ensure_items(self, order: Order) -> list[OrderItem]:
        """Return the order's per-unit rows, lazily creating any that are missing.

        Creation is idempotent on ``(order_id, unit_index)``: an order created
        before this table existed, or one only partially expanded, is topped up
        to ``quantity`` rows without duplicating the ones already there.
        """
        items = await self.items.list_for_order(order.id)
        have = len(items)
        want = max(1, order.quantity or 1)
        for unit_index in range(have, want):
            item = OrderItem(
                order_id=order.id,
                unit_index=unit_index,
                status=OrderItemStatus.PENDING,
            )
            await self.items.add(item)
            items.append(item)
        return items

    # ---- per-unit delivery (inventory-first, then JIT) --------------------
    async def _deliver_unit(self, order: Order, item: OrderItem) -> _UnitOutcome:
        """Obtain and deliver a code for one unit. No order-level side effects."""
        inventory, source, reason = await self._obtain_stock(order)
        if inventory is None:
            item.last_error = (reason or "out of stock")[:1024]
            return _UnitOutcome.NO_STOCK

        try:
            delivery = await self._deliver(order, inventory.code)
        except Exception as exc:  # noqa: BLE001 — delivery is best-effort
            await self.inventory.release(inventory.id)
            item.last_error = f"delivery error: {exc}"[:1024]
            return _UnitOutcome.DELIVERY_FAILED

        if not delivery.success:
            await self.inventory.release(inventory.id)
            item.last_error = "delivery rejected by marketplace"
            return _UnitOutcome.DELIVERY_FAILED

        await self.inventory.mark_sold(inventory.id)
        item.status = OrderItemStatus.DELIVERED
        item.inventory_id = inventory.id
        item.fulfillment_source = source
        item.delivery_reference = delivery.reference
        item.delivered_at = utcnow()
        item.last_error = None
        return _UnitOutcome.DELIVERED

    async def _obtain_stock(
        self, order: Order
    ) -> tuple[Inventory | None, FulfillmentSource | None, str | None]:
        """Reserve one code for a unit: our own stock first, then JIT sourcing.

        Returns ``(inventory, source, reason)`` — ``inventory`` is ``None`` when
        nothing could be obtained, with ``reason`` explaining why. Has no
        order-level side effects (no status change, no commit).
        """
        item = await self.inventory.reserve_one(order.product_id, order.id)
        if item is not None:
            return item, FulfillmentSource.MANUAL, None

        if not settings.JIT_ENABLED:
            return None, None, "out of stock; JIT disabled"

        try:
            result = await self.sourcing.source(
                order.product_id, order.provider, order.id
            )
            return result.inventory, FulfillmentSource.JIT, None
        except (SourcingUnavailable, InsufficientFunds) as exc:
            return None, None, str(exc)

    # ---- order-level finalisation ----------------------------------------
    async def _finalize(
        self, order: Order, items: list[OrderItem], blocking: _UnitOutcome | None
    ) -> FulfillResult:
        delivered = [i for i in items if i.status is OrderItemStatus.DELIVERED]

        if len(delivered) == len(items):
            return await self._complete(order, delivered)

        # Some units remain. If none delivered, preserve the single-unit failure
        # semantics (out-of-stock -> awaiting; delivery failure -> retry/fail).
        # If we delivered some, the order must never regress to FAILED (that
        # would lose the delivered codes), so it awaits stock for the remainder.
        reason = self._blocking_reason(items, blocking)
        if delivered:
            return await self._await_stock(
                order,
                f"partial delivery {len(delivered)}/{len(items)}: {reason}",
                delivered=delivered,
            )
        if blocking is _UnitOutcome.DELIVERY_FAILED:
            return await self._retry_or_fail(order, reason)
        return await self._await_stock(order, reason)

    async def _complete(
        self, order: Order, delivered: list[OrderItem]
    ) -> FulfillResult:
        first = delivered[0]
        order.status = OrderStatus.DELIVERED
        order.fulfillment_source = first.fulfillment_source
        order.inventory_id = first.inventory_id
        order.delivered_at = utcnow()
        order.last_error = None
        await self.alerts.resolve_by_dedupe(f"awaiting-{order.id}")
        await record_event(
            self.session,
            LogLevel.INFO,
            "fulfillment",
            f"Order {order.id} delivered ({len(delivered)} unit(s))",
            {"order_id": order.id, "provider": order.provider},
        )

        # Revenue is credited once, for the whole order, when it is fully
        # delivered (mirrors the original single-unit behaviour).
        if order.total is not None:
            await self.wallet.credit(
                order.provider,
                order.currency or settings.BASE_CURRENCY,
                Decimal(order.total),
                order_id=order.id,
                type=TransactionType.SALE_REVENUE,
                reference=first.delivery_reference,
            )

        await self.session.commit()
        source = first.fulfillment_source
        log.info(
            "fulfillment.delivered",
            order_id=order.id,
            units=len(delivered),
            source=source.value if source else None,
        )
        return FulfillResult(
            order.id,
            True,
            order.status.value,
            source=source.value if source else None,
        )

    @staticmethod
    def _blocking_reason(
        items: list[OrderItem], blocking: _UnitOutcome | None
    ) -> str:
        for item in items:
            if item.status is not OrderItemStatus.DELIVERED and item.last_error:
                return item.last_error
        return "awaiting stock" if blocking is _UnitOutcome.NO_STOCK else "delivery failed"

    async def _deliver(self, order: Order, code: str) -> DeliveryResult:
        adapter = build_adapter(order.provider, resolve_credentials(order.provider))
        try:
            return await adapter.deliver(
                order.external_order_id, code, marketplace_sku=order.marketplace_sku
            )
        finally:
            await adapter.aclose()

    # ---- failure handling -------------------------------------------------
    async def _await_stock(
        self,
        order: Order,
        message: str,
        *,
        delivered: list[OrderItem] | None = None,
    ) -> FulfillResult:
        order.status = OrderStatus.AWAITING_STOCK
        order.last_error = message[:1024]
        # On a partial delivery keep the order pointing at a delivered unit so
        # the dashboard still reflects what went out.
        if delivered:
            order.fulfillment_source = delivered[0].fulfillment_source
            order.inventory_id = delivered[0].inventory_id
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
        return FulfillResult(
            order.id, False, order.status.value, error=order.last_error
        )

    async def _retry_or_fail(self, order: Order, message: str) -> FulfillResult:
        order.last_error = message[:1024]
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
