"""Runtime kill-switch for the pricing engine.

The engine's on/off state lives in Redis so an operator (or the Milestone-5
dashboard) can halt all automated repricing instantly without a restart. When
Redis has no explicit value, the ``PRICING_ENGINE_ENABLED`` setting decides.
"""

from __future__ import annotations

from typing import Any

from app.core.config import settings
from app.core.logging import get_logger
from app.core.redis import get_redis_client

log = get_logger(__name__)

ENGINE_FLAG_KEY = "pricing:engine:enabled"
_TRUE = {"1", "true", "yes", "on"}


async def is_engine_enabled(redis: Any | None = None) -> bool:
    client = redis or get_redis_client()
    try:
        value = await client.get(ENGINE_FLAG_KEY)
    except Exception as exc:  # noqa: BLE001 — degrade to the static setting
        log.warning("pricing.killswitch_read_failed", error=str(exc))
        return settings.PRICING_ENGINE_ENABLED
    if value is None:
        return settings.PRICING_ENGINE_ENABLED
    return str(value).strip().lower() in _TRUE


async def set_engine_enabled(enabled: bool, redis: Any | None = None) -> bool:
    client = redis or get_redis_client()
    try:
        await client.set(ENGINE_FLAG_KEY, "1" if enabled else "0")
        log.info("pricing.killswitch_set", enabled=enabled)
    except Exception as exc:  # noqa: BLE001 — Redis down: degrade, don't 500
        # When Redis is unavailable the scan worker cannot acquire its lock and
        # therefore cannot run anyway, so failing to persist the flag is safe.
        log.warning("pricing.killswitch_set_failed", enabled=enabled, error=str(exc))
    return enabled
