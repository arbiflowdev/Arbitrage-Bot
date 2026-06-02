"""Shared async HTTP client for marketplace adapters.

Centralises the cross-cutting concerns every provider needs: timeouts,
exponential-backoff retries (honouring ``Retry-After``), proactive Redis-backed
rate limiting, and translation of transport/HTTP failures into the normalized
integration exceptions. Adapters call :meth:`request_json` and never touch
httpx directly.
"""

from __future__ import annotations

import asyncio
import random
import time
from typing import Any

import httpx

from app.core.config import settings
from app.core.logging import get_logger
from app.core.redis import get_redis_client
from app.integrations.exceptions import (
    ProviderAPIError,
    ProviderUnavailable,
    RateLimitExceeded,
)

log = get_logger(__name__)

# Status codes worth retrying: rate limit + transient server errors.
_RETRYABLE_STATUS = {429, 500, 502, 503, 504}


class MarketplaceHTTPClient:
    """Thin, resilient wrapper around ``httpx.AsyncClient`` for one provider."""

    def __init__(
        self,
        provider: str,
        base_url: str,
        *,
        default_headers: dict[str, str] | None = None,
        timeout: float | None = None,
        max_retries: int | None = None,
        backoff: float | None = None,
        rate_limit_per_minute: int | None = None,
    ) -> None:
        self.provider = provider
        self.base_url = base_url.rstrip("/")
        self.default_headers = default_headers or {}
        self.timeout = timeout if timeout is not None else settings.HTTP_TIMEOUT_SECONDS
        self.max_retries = (
            max_retries if max_retries is not None else settings.HTTP_MAX_RETRIES
        )
        self.backoff = (
            backoff if backoff is not None else settings.HTTP_RETRY_BACKOFF_SECONDS
        )
        self.rate_limit_per_minute = rate_limit_per_minute
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        if self._client is None:
            self._client = httpx.AsyncClient(
                base_url=self.base_url,
                timeout=self.timeout,
                headers=self.default_headers,
            )
        return self._client

    async def aclose(self) -> None:
        if self._client is not None:
            await self._client.aclose()
            self._client = None

    # ------------------------------------------------------------------
    # Rate limiting (fixed window per minute, best-effort via Redis)
    # ------------------------------------------------------------------
    async def _enforce_rate_limit(self) -> None:
        if not self.rate_limit_per_minute:
            return
        try:
            client = get_redis_client()
            window = int(time.time() // 60)
            key = f"ratelimit:{self.provider}:{window}"
            count = await client.incr(key)
            if count == 1:
                await client.expire(key, 60)
        except Exception as exc:  # noqa: BLE001 — Redis down must not block traffic
            log.warning("ratelimit.unavailable", provider=self.provider, error=str(exc))
            return

        if count > self.rate_limit_per_minute:
            raise RateLimitExceeded(
                f"Local rate limit of {self.rate_limit_per_minute}/min exceeded "
                f"for provider '{self.provider}'.",
                retry_after=60.0,
            )

    # ------------------------------------------------------------------
    # Requests
    # ------------------------------------------------------------------
    async def request(self, method: str, path: str, **kwargs: Any) -> httpx.Response:
        """Perform a request with retries; raise normalized errors on failure."""
        await self._enforce_rate_limit()
        client = await self._get_client()

        attempt = 0
        while True:
            attempt += 1
            try:
                response = await client.request(method, path, **kwargs)
            except httpx.TimeoutException as exc:
                if attempt > self.max_retries:
                    raise ProviderUnavailable(
                        f"'{self.provider}' request timed out after {attempt} "
                        f"attempts."
                    ) from exc
                await self._sleep_backoff(attempt)
                continue
            except httpx.TransportError as exc:
                if attempt > self.max_retries:
                    raise ProviderUnavailable(
                        f"'{self.provider}' is unreachable: {exc}"
                    ) from exc
                await self._sleep_backoff(attempt)
                continue

            if (
                response.status_code in _RETRYABLE_STATUS
                and attempt <= self.max_retries
            ):
                await self._sleep_backoff(attempt, self._parse_retry_after(response))
                continue

            if response.status_code == 429:
                raise RateLimitExceeded(
                    f"'{self.provider}' returned HTTP 429 (rate limited).",
                    retry_after=self._parse_retry_after(response),
                )
            if response.status_code >= 400:
                raise ProviderAPIError(
                    f"'{self.provider}' API error: HTTP {response.status_code}.",
                    status_code=response.status_code,
                    payload=self._safe_body(response),
                )
            return response

    async def request_json(self, method: str, path: str, **kwargs: Any) -> Any:
        """Like :meth:`request` but returns parsed JSON (or None for empty body)."""
        response = await self.request(method, path, **kwargs)
        if not response.content:
            return None
        try:
            return response.json()
        except ValueError as exc:
            raise ProviderAPIError(
                f"'{self.provider}' returned a non-JSON response.",
                status_code=response.status_code,
            ) from exc

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------
    async def _sleep_backoff(
        self, attempt: int, retry_after: float | None = None
    ) -> None:
        if retry_after is not None:
            delay = retry_after
        else:
            delay = self.backoff * (2 ** (attempt - 1))
            delay += random.uniform(0, self.backoff)  # jitter to avoid thundering herd
        await asyncio.sleep(delay)

    @staticmethod
    def _parse_retry_after(response: httpx.Response) -> float | None:
        value = response.headers.get("Retry-After")
        if not value:
            return None
        try:
            return float(value)
        except ValueError:
            return None

    @staticmethod
    def _safe_body(response: httpx.Response) -> Any:
        try:
            return response.json()
        except ValueError:
            return response.text[:500]
