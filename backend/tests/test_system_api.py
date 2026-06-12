"""System status + global kill-switch endpoints."""

from __future__ import annotations

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_system_status_requires_admin(client: AsyncClient) -> None:
    assert (await client.get("/api/v1/system/status")).status_code == 401


@pytest.mark.asyncio
async def test_status_and_global_kill_switch(
    client: AsyncClient, admin_headers: dict[str, str]
) -> None:
    status_resp = await client.get("/api/v1/system/status", headers=admin_headers)
    assert status_resp.status_code == 200, status_resp.text
    body = status_resp.json()
    assert "pricing_enabled" in body and "fulfillment_enabled" in body

    off = await client.post(
        "/api/v1/system/kill-switch", headers=admin_headers, json={"enabled": False}
    )
    assert off.status_code == 200
    assert off.json()["pricing_enabled"] is False
    assert off.json()["fulfillment_enabled"] is False

    on = await client.post(
        "/api/v1/system/kill-switch", headers=admin_headers, json={"enabled": True}
    )
    assert on.json()["pricing_enabled"] is True
    assert on.json()["fulfillment_enabled"] is True
