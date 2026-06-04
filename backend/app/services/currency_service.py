"""Multi-currency conversion with an FX safety buffer.

G2G trades mainly in USD while Kinguin and Eneba use EUR, so every observed
price is converted into a single base currency (EUR) before the engine compares
anything. Rates come from a free exchange-rate feed (ExchangeRate-API's
``open.er-api.com``), cached in Redis for ``EXCHANGE_RATE_TTL_SECONDS``. A
``CURRENCY_BUFFER_PERCENT`` is added on top of foreign conversions so intra-day
swings cannot quietly erode margin.

Rates are expressed as *units of the currency per 1 unit of base* — exactly the
shape ``open.er-api.com/v6/latest/EUR`` returns under ``rates``.
"""

from __future__ import annotations

import json
from decimal import ROUND_HALF_UP, Decimal
from typing import Any

import httpx

from app.core.config import settings
from app.core.logging import get_logger

log = get_logger(__name__)

_Q = Decimal("0.0001")


class CurrencyService:
    def __init__(
        self,
        *,
        base_currency: str | None = None,
        buffer_percent: Decimal | None = None,
        static_rates: dict[str, Any] | None = None,
        redis: Any | None = None,
    ) -> None:
        self.base = (base_currency or settings.BASE_CURRENCY).upper()
        self.buffer = (
            buffer_percent
            if buffer_percent is not None
            else settings.CURRENCY_BUFFER_PERCENT
        )
        self._redis = redis
        # When static rates are supplied (tests / offline), use them verbatim
        # and never hit the network.
        self._static: dict[str, Decimal] | None = (
            {k.upper(): Decimal(str(v)) for k, v in static_rates.items()}
            if static_rates is not None
            else None
        )
        if self._static is not None:
            self._static.setdefault(self.base, Decimal("1"))
        self._cache: dict[str, Decimal] | None = self._static

    def _q(self, value: Decimal) -> Decimal:
        return Decimal(value).quantize(_Q, rounding=ROUND_HALF_UP)

    # ---- rate sourcing ----------------------------------------------------
    async def _rates(self) -> dict[str, Decimal]:
        if self._cache:
            return self._cache

        cache_key = f"fx:rates:{self.base}"
        if self._redis is not None:
            try:
                cached = await self._redis.get(cache_key)
                if cached:
                    data = json.loads(cached)
                    self._cache = {k: Decimal(str(v)) for k, v in data.items()}
                    return self._cache
            except Exception as exc:  # noqa: BLE001 — cache is best-effort
                log.warning("fx.cache_read_failed", error=str(exc))

        rates = await self._fetch_rates()
        if self._redis is not None and rates:
            try:
                await self._redis.set(
                    cache_key,
                    json.dumps({k: str(v) for k, v in rates.items()}),
                    ex=settings.EXCHANGE_RATE_TTL_SECONDS,
                )
            except Exception as exc:  # noqa: BLE001
                log.warning("fx.cache_write_failed", error=str(exc))
        self._cache = rates
        return rates

    async def _fetch_rates(self) -> dict[str, Decimal]:
        url = f"{settings.EXCHANGE_RATE_API_URL.rstrip('/')}/{self.base}"
        try:
            async with httpx.AsyncClient(timeout=settings.HTTP_TIMEOUT_SECONDS) as c:
                resp = await c.get(url)
                resp.raise_for_status()
                body = resp.json()
            raw = body.get("rates") or body.get("conversion_rates") or {}
            rates = {k.upper(): Decimal(str(v)) for k, v in raw.items()}
            rates.setdefault(self.base, Decimal("1"))
            log.info("fx.rates_fetched", base=self.base, count=len(rates))
            return rates
        except Exception as exc:  # noqa: BLE001 — degrade gracefully
            log.warning("fx.fetch_failed", base=self.base, error=str(exc))
            # Without rates we can only trust base-currency values.
            return {self.base: Decimal("1")}

    # ---- conversion -------------------------------------------------------
    async def convert(
        self, amount: Decimal, from_ccy: str, to_ccy: str
    ) -> Decimal:
        from_ccy, to_ccy = from_ccy.upper(), to_ccy.upper()
        if from_ccy == to_ccy:
            return self._q(amount)
        rates = await self._rates()
        rf, rt = rates.get(from_ccy), rates.get(to_ccy)
        if not rf or not rt:
            return self._q(amount)  # unknown pair -> pass through
        return self._q(amount / rf * rt)

    async def to_base(
        self, amount: Decimal, from_ccy: str, *, apply_buffer: bool = True
    ) -> Decimal:
        """Convert ``amount`` into the base currency, optionally buffered.

        Values already in the base currency are returned unchanged (no buffer).
        Unknown currencies are passed through conservatively rather than raising.
        """
        from_ccy = from_ccy.upper()
        if from_ccy == self.base:
            return self._q(amount)
        rates = await self._rates()
        rate = rates.get(from_ccy)
        if not rate:
            return self._q(amount)
        base_amount = amount / rate
        if apply_buffer and self.buffer:
            base_amount *= Decimal("1") + self.buffer / Decimal("100")
        return self._q(base_amount)
