"""Runtime fulfillment kill-switch falls back to settings when Redis is empty."""

from __future__ import annotations

import pytest

from app.services import fulfillment_control


class _FakeRedis:
    def __init__(self) -> None:
        self.store: dict[str, str] = {}

    async def get(self, key: str):
        return self.store.get(key)

    async def set(self, key: str, value: str) -> None:
        self.store[key] = value


@pytest.mark.asyncio
async def test_defaults_to_setting_when_unset() -> None:
    redis = _FakeRedis()
    assert await fulfillment_control.is_fulfillment_enabled(redis) is True


@pytest.mark.asyncio
async def test_set_then_read_roundtrips() -> None:
    redis = _FakeRedis()
    await fulfillment_control.set_fulfillment_enabled(False, redis)
    assert await fulfillment_control.is_fulfillment_enabled(redis) is False
    await fulfillment_control.set_fulfillment_enabled(True, redis)
    assert await fulfillment_control.is_fulfillment_enabled(redis) is True
