"""Order polling worker — the safety net behind order webhooks.

Periodically pulls recent orders from each live marketplace and ingests them, so
a dropped or never-delivered webhook never means a missed sale. Ingestion is
idempotent on ``(provider, external_order_id)``, so re-polling the same order is
harmless. The fulfillment worker then delivers whatever this ingests.

Polling only runs in ``live`` mode; in ``mock`` mode orders arrive via the
webhook/ingest API so demos stay clean.
"""

from __future__ import annotations

import asyncio

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.core.logging import get_logger
from app.core.redis import acquire_lock
from app.integrations import SUPPORTED_PROVIDERS, build_adapter, resolve_credentials
from app.services.fulfillment_control import is_fulfillment_enabled
from app.services.order_intake_service import OrderIntakeService

log = get_logger(__name__)


class OrderPollWorker:
    def __init__(self, interval_seconds: int | None = None) -> None:
        self.interval = interval_seconds or settings.FULFILLMENT_POLL_INTERVAL_SECONDS
        self._task: asyncio.Task[None] | None = None
        self._stop = asyncio.Event()

    def start(self) -> None:
        if self._task is None or self._task.done():
            self._stop.clear()
            self._task = asyncio.create_task(self._run(), name="order-poll-worker")
            log.info("fulfillment.poll_worker_started", interval_seconds=self.interval)

    async def stop(self) -> None:
        self._stop.set()
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
            self._task = None
            log.info("fulfillment.poll_worker_stopped")

    async def _run(self) -> None:
        try:
            await asyncio.wait_for(self._stop.wait(), timeout=min(8, self.interval))
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
            if not await is_fulfillment_enabled():
                return
            if not settings.FULFILLMENT_ENABLED or settings.MARKETPLACE_MODE != "live":
                return
            lock = acquire_lock(
                "order-poll", timeout=self.interval, blocking_timeout=0
            )
            if not await lock.acquire():
                return
            try:
                ingested = 0
                async with AsyncSessionLocal() as session:
                    intake = OrderIntakeService(session)
                    for provider in SUPPORTED_PROVIDERS:
                        ingested += await self._poll_provider(provider, intake)
                    await session.commit()
                if ingested:
                    log.info("fulfillment.poll", ingested=ingested)
            finally:
                try:
                    await lock.release()
                except Exception:  # noqa: BLE001
                    pass
        except Exception as exc:  # noqa: BLE001 — never let the loop die
            log.warning("fulfillment.poll_failed", error=str(exc))

    async def _poll_provider(self, provider: str, intake: OrderIntakeService) -> int:
        adapter = build_adapter(provider, resolve_credentials(provider))
        count = 0
        try:
            orders = await adapter.fetch_orders(limit=50)
        finally:
            await adapter.aclose()
        for order in orders:
            _, created = await intake.ingest_normalized(provider, order)
            count += int(created)
        return count
