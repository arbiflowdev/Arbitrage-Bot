"""The SPA is served at / and as a fallback; API + docs are unaffected."""

from __future__ import annotations

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_root_serves_spa(client: AsyncClient) -> None:
    resp = await client.get("/")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]


@pytest.mark.asyncio
async def test_unknown_path_falls_back_to_spa(client: AsyncClient) -> None:
    resp = await client.get("/orders")
    assert resp.status_code == 200
    assert "text/html" in resp.headers["content-type"]


@pytest.mark.asyncio
async def test_api_metadata_moved_to_api(client: AsyncClient) -> None:
    resp = await client.get("/api")
    assert resp.status_code == 200
    assert resp.json()["api"].endswith("/v1")


@pytest.mark.asyncio
async def test_unknown_api_path_is_404_not_spa(client: AsyncClient) -> None:
    resp = await client.get("/api/v1/does-not-exist")
    assert resp.status_code == 404
