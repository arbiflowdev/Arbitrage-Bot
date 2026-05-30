"""Smoke tests for the health endpoint."""

from __future__ import annotations

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_root_lists_metadata(client: AsyncClient) -> None:
    resp = await client.get("/")
    assert resp.status_code == 200
    body = resp.json()
    assert body["docs"] == "/docs"
    assert body["api"].endswith("/v1")


@pytest.mark.asyncio
async def test_health_returns_component_breakdown(client: AsyncClient) -> None:
    resp = await client.get("/api/v1/health")
    assert resp.status_code == 200
    body = resp.json()

    # Status is "ok" or "degraded" depending on whether Redis is up in CI.
    assert body["status"] in {"ok", "degraded"}
    assert body["app"]
    assert body["version"]
    assert "database" in body["components"]
    assert "redis" in body["components"]
    # The database component must be reachable in tests.
    assert body["components"]["database"]["status"] == "ok"
