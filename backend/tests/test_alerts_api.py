"""API tests for the Milestone 5 alerts endpoints."""

from __future__ import annotations

import pytest
from httpx import AsyncClient
from sqlalchemy import delete

from app.core.database import AsyncSessionLocal
from app.models.alert import Alert, AlertSeverity, AlertType
from app.services.alert_service import AlertService


async def _seed_alert() -> int:
    async with AsyncSessionLocal() as s:
        await s.execute(delete(Alert))
        svc = AlertService(s)
        a = await svc.raise_alert(
            AlertType.ORDER_FAILED, AlertSeverity.CRITICAL, "Failed", "msg"
        )
        await s.commit()
        return a.id


@pytest.mark.asyncio
async def test_alerts_require_admin(client: AsyncClient) -> None:
    assert (await client.get("/api/v1/alerts")).status_code == 401


@pytest.mark.asyncio
async def test_list_acknowledge_resolve_and_summary(
    client: AsyncClient, admin_headers: dict[str, str]
) -> None:
    aid = await _seed_alert()

    listing = await client.get("/api/v1/alerts", headers=admin_headers)
    assert listing.status_code == 200, listing.text
    assert any(a["id"] == aid for a in listing.json())

    summary = await client.get("/api/v1/alerts/summary", headers=admin_headers)
    assert summary.status_code == 200
    assert summary.json()["critical"] >= 1

    ack = await client.post(f"/api/v1/alerts/{aid}/acknowledge", headers=admin_headers)
    assert ack.status_code == 200
    assert ack.json()["status"] == "acknowledged"

    res = await client.post(f"/api/v1/alerts/{aid}/resolve", headers=admin_headers)
    assert res.status_code == 200
    assert res.json()["status"] == "resolved"
