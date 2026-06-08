"""Background fulfillment worker.

Periodically sweeps retryable orders (RECEIVED and AWAITING_STOCK) and runs them
through the fulfillment pipeline, so a missed webhook, a transient delivery
failure, or an out-of-stock order that has since been restocked all make
progress without manual intervention. A Redis lock ensures a single instance
sweeps at a time; the loop is resilient and never dies on error.
"""

from __future__ import annotations

import asyncio

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.core.logging import get_logger
from app.core.redis import acquire_lock
from app.models.order import OrderStatus
from app.repositories.order_repository import OrderRepository
from app.services.fulfillment_service import FulfillmentService

log = get_logger(__name__)

_RETRYABLE = [OrderStatus.RECEIVED, OrderStatus.AWAITING_STOCK]


class FulfillmentWorker:
    def __init__(self, interval_seconds: int | None = None) -> None:
        self.interval = interval_seconds or settings.FULFILLMENT_POLL_INTERVAL_SECONDS
        self._task: asyncio.Task[None] | None = None
        self._stop = asyncio.Event()

    def start(self) -> None:
        if self._task is None or self._task.done():
            self._stop.clear()
            self._task = asyncio.create_task(self._run(), name="fulfillment-worker")
            log.info("fulfillment.worker_started", interval_seconds=self.interval)

    async def stop(self) -> None:
        self._stop.set()
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
            self._task = None
            log.info("fulfillment.worker_stopped")

    async def _run(self) -> None:
        try:
            await asyncio.wait_for(self._stop.wait(), timeout=min(5, self.interval))
        except TimeoutError:
            pass
        while not self._stop.is_set():
            await self._tick()
            try:
                await asyncio.wait_for(self._stop.wait(), timeout=self.interval)
            except TimeoutError:
                continue

    async def _tick(self) -> None:
        try:
            if not settings.FULFILLMENT_ENABLED:
                return
            lock = acquire_lock(
                "fulfillment-sweep", timeout=self.interval, blocking_timeout=0
            )
            if not await lock.acquire():
                return
            try:
                async with AsyncSessionLocal() as session:
                    orders = await OrderRepository(session).list_by_status(
                        _RETRYABLE, limit=200
                    )
                    service = FulfillmentService(session)
                    delivered = 0
                    for order in orders:
                        if order.attempts >= settings.FULFILLMENT_MAX_ATTEMPTS:
                            continue
                        result = await service.fulfill(order.id)
                        delivered += int(result.delivered)
                if orders:
                    log.info(
                        "fulfillment.sweep",
                        candidates=len(orders),
                        delivered=delivered,
                    )
            finally:
                try:
                    await lock.release()
                except Exception:  # noqa: BLE001
                    pass
        except Exception as exc:  # noqa: BLE001 — never let the loop die
            log.warning("fulfillment.sweep_failed", error=str(exc))
