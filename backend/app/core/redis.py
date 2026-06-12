"""Async Redis client with helpers prepared for caching, distributed
locking, and async queue use-cases that arrive in later milestones.
"""

from __future__ import annotations

from typing import Any

import redis.asyncio as aioredis
from redis.asyncio.client import Redis
from redis.asyncio.lock import Lock

from app.core.config import settings

_redis_client: Redis | None = None


def get_redis_client() -> Redis:
    """Return the process-wide async Redis client (lazy-initialised)."""
    global _redis_client
    if _redis_client is None:
        _redis_client = aioredis.from_url(
            settings.REDIS_URL,
            encoding="utf-8",
            decode_responses=True,
            health_check_interval=30,
            # Fail fast when Redis is unreachable (e.g. not running in local dev)
            # so kill-switch/status reads fall back to settings in <1s instead of
            # blocking for seconds on a connection attempt.
            socket_connect_timeout=0.5,
            socket_timeout=2.0,
            retry_on_timeout=False,
        )
    return _redis_client


async def close_redis_client() -> None:
    """Close the Redis client on application shutdown."""
    global _redis_client
    if _redis_client is not None:
        await _redis_client.aclose()
        _redis_client = None


async def ping_redis() -> bool:
    """Return True if Redis is reachable."""
    client = get_redis_client()
    try:
        return bool(await client.ping())
    except Exception:  # noqa: BLE001
        return False


# ---------------------------------------------------------------------------
# Helpers — thin wrappers so the rest of the codebase does not need to know
# about the underlying client. Later milestones (repricing engine, JIT
# sourcing, order fulfilment) will build on these primitives.
# ---------------------------------------------------------------------------


async def cache_set(key: str, value: str, ttl_seconds: int | None = None) -> None:
    """Set a cache value with optional TTL."""
    await get_redis_client().set(key, value, ex=ttl_seconds)


async def cache_get(key: str) -> str | None:
    """Get a cache value or None."""
    value: Any = await get_redis_client().get(key)
    return value if value is None else str(value)


async def cache_delete(*keys: str) -> int:
    """Delete one or more keys; returns number of keys removed."""
    if not keys:
        return 0
    return int(await get_redis_client().delete(*keys))


def acquire_lock(
    name: str,
    timeout: float | None = 30.0,
    blocking_timeout: float | None = 5.0,
) -> Lock:
    """Return a redis-py Lock object for use as `async with`.

    The lock is fair, auto-expires after ``timeout`` seconds, and only blocks
    up to ``blocking_timeout`` seconds while trying to acquire.
    """
    return get_redis_client().lock(
        name=f"lock:{name}",
        timeout=timeout,
        blocking_timeout=blocking_timeout,
    )


async def enqueue(queue: str, payload: str) -> int:
    """Push a job payload onto a Redis list (FIFO queue scaffold)."""
    return int(await get_redis_client().rpush(f"queue:{queue}", payload))
