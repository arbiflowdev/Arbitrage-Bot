"""Runtime kill-switch for the fulfillment + order-poll workers.

The flag lives in Redis so the dashboard can halt all automated fulfillment
instantly without a restart. With no Redis value, ``FULFILLMENT_ENABLED`` from
settings decides.
"""

from __future__ import annotations

from typing import Any

from app.core.config import settings
from app.core.logging import get_logger
from app.core.redis import get_redis_client

log = get_logger(__name__)

FULFILLMENT_FLAG_KEY = "fulfillment:enabled"
_TRUE = {"1", "true", "yes", "on"}


async def is_fulfillment_enabled(redis: Any | None = None) -> bool:
    client = redis or get_redis_client()
    try:
        value = await client.get(FULFILLMENT_FLAG_KEY)
    except Exception as exc:  # noqa: BLE001
        log.warning("fulfillment.killswitch_read_failed", error=str(exc))
        return settings.FULFILLMENT_ENABLED
    if value is None:
        return settings.FULFILLMENT_ENABLED
    return str(value).strip().lower() in _TRUE


async def set_fulfillment_enabled(enabled: bool, redis: Any | None = None) -> bool:
    client = redis or get_redis_client()
    try:
        await client.set(FULFILLMENT_FLAG_KEY, "1" if enabled else "0")
        log.info("fulfillment.killswitch_set", enabled=enabled)
    except Exception as exc:  # noqa: BLE001
        log.warning("fulfillment.killswitch_set_failed", enabled=enabled, error=str(exc))
    return enabled
