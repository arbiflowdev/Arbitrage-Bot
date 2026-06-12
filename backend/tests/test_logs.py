"""record_event persists, and GET /logs lists with filters."""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy import delete

from app.core.database import AsyncSessionLocal
from app.models.log import Log, LogLevel
from app.services.event_log_service import record_event


@pytest.mark.asyncio
async def test_record_event_persists_and_lists(
    client: AsyncClient, admin_headers: dict[str, str]
) -> None:
    async with AsyncSessionLocal() as s:
        await s.execute(delete(Log))
        await s.commit()
    async with AsyncSessionLocal() as s:
        await record_event(s, LogLevel.ERROR, "fulfillment", "delivery exploded")
        await record_event(s, LogLevel.INFO, "pricing", "scan ok")
        await s.commit()

    all_logs = await client.get("/api/v1/logs", headers=admin_headers)
    assert all_logs.status_code == 200, all_logs.text
    assert len(all_logs.json()) >= 2

    errors = await client.get("/api/v1/logs?level=ERROR", headers=admin_headers)
    assert errors.status_code == 200
    assert all(row["level"] == "ERROR" for row in errors.json())


@pytest.mark.asyncio
async def test_logs_require_admin(client: AsyncClient) -> None:
    assert (await client.get("/api/v1/logs")).status_code == 401
