"""Automated 60-second pricing scan worker.

Runs :class:`~app.services.pricing_service.PricingService` on a fixed interval.
A Redis lock guarantees only one scan runs across all app instances, and the
kill-switch is honoured every tick so the engine can be halted instantly. The
worker is resilient: any error in a cycle is logged and the loop continues.
"""

from __future__ import annotations

import asyncio

from app.core.config import settings
from app.core.database import AsyncSessionLocal
from app.core.logging import get_logger
from app.core.redis import acquire_lock
from app.services.pricing_control import is_engine_enabled
from app.services.pricing_service import PricingService

log = get_logger(__name__)


class PricingScanWorker:
    def __init__(self, interval_seconds: int | None = None) -> None:
        self.interval = interval_seconds or settings.PRICING_SCAN_INTERVAL_SECONDS
        self._task: asyncio.Task[None] | None = None
        self._stop = asyncio.Event()

    def start(self) -> None:
        if self._task is None or self._task.done():
            self._stop.clear()
            self._task = asyncio.create_task(self._run(), name="pricing-scan-worker")
            log.info("pricing.worker_started", interval_seconds=self.interval)

    async def stop(self) -> None:
        self._stop.set()
        if self._task is not None:
            self._task.cancel()
            try:
                await self._task
            except (asyncio.CancelledError, Exception):  # noqa: BLE001
                pass
            self._task = None
            log.info("pricing.worker_stopped")

    async def _run(self) -> None:
        # Stagger the first scan slightly so startup work settles first.
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
            if not await is_engine_enabled():
                log.debug("pricing.scan_skipped_disabled")
                return
            # Only one instance scans at a time.
            lock = acquire_lock(
                "pricing-scan", timeout=self.interval, blocking_timeout=0
            )
            acquired = await lock.acquire()
            if not acquired:
                log.debug("pricing.scan_skipped_locked")
                return
            try:
                async with AsyncSessionLocal() as session:
                    summary = await PricingService(session).scan()
                log.info(
                    "pricing.scan_tick",
                    scanned=summary.scanned,
                    applied=summary.applied,
                )
            finally:
                try:
                    await lock.release()
                except Exception:  # noqa: BLE001 — lock may have expired
                    pass
        except Exception as exc:  # noqa: BLE001 — never let the loop die
            log.warning("pricing.scan_tick_failed", error=str(exc))
