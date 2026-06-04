"""Tests for marketplace sync + webhook APIs (mock mode)."""

from __future__ import annotations

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_list_marketplaces(
    client: AsyncClient, admin_headers: dict[str, str]
) -> None:
    resp = await client.get("/api/v1/marketplaces", headers=admin_headers)
    assert resp.status_code == 200, resp.text
    providers = {m["provider"] for m in resp.json()}
    assert {"kinguin", "g2g"}.issubset(providers)
    for m in resp.json():
        assert m["mode"] == "mock"
        assert m["supported"] is True


@pytest.mark.asyncio
async def test_sync_prices_then_list(
    client: AsyncClient, admin_headers: dict[str, str]
) -> None:
    resp = await client.post(
        "/api/v1/marketplaces/kinguin/sync/prices", headers=admin_headers
    )
    assert resp.status_code == 200, resp.text
    result = resp.json()
    assert result["operation"] == "prices"
    assert result["mode"] == "mock"
    assert result["fetched"] > 0
    assert result["upserted"] > 0

    listing = await client.get(
        "/api/v1/marketplace-prices?provider=kinguin", headers=admin_headers
    )
    assert listing.status_code == 200
    rows = listing.json()
    assert len(rows) > 0
    assert rows[0]["provider"] == "kinguin"


@pytest.mark.asyncio
async def test_sync_prices_is_idempotent_upsert(
    client: AsyncClient, admin_headers: dict[str, str]
) -> None:
    await client.post(
        "/api/v1/marketplaces/g2g/sync/prices", headers=admin_headers
    )
    await client.post(
        "/api/v1/marketplaces/g2g/sync/prices", headers=admin_headers
    )
    rows = (
        await client.get(
            "/api/v1/marketplace-prices?provider=g2g", headers=admin_headers
        )
    ).json()
    skus = [r["marketplace_sku"] for r in rows]
    assert len(skus) == len(set(skus))  # no duplicates after a second sync


@pytest.mark.asyncio
async def test_sync_listings_then_list(
    client: AsyncClient, admin_headers: dict[str, str]
) -> None:
    resp = await client.post(
        "/api/v1/marketplaces/kinguin/sync/listings", headers=admin_headers
    )
    assert resp.status_code == 200, resp.text
    assert resp.json()["fetched"] > 0

    listings = await client.get(
        "/api/v1/listings?provider=kinguin", headers=admin_headers
    )
    assert listings.status_code == 200
    assert len(listings.json()) > 0


@pytest.mark.asyncio
async def test_sync_unknown_provider_404(
    client: AsyncClient, admin_headers: dict[str, str]
) -> None:
    resp = await client.post(
        "/api/v1/marketplaces/nosuchprovider/sync/prices", headers=admin_headers
    )
    assert resp.status_code == 404


@pytest.mark.asyncio
async def test_fetch_orders_mock(
    client: AsyncClient, admin_headers: dict[str, str]
) -> None:
    resp = await client.get(
        "/api/v1/marketplaces/kinguin/orders", headers=admin_headers
    )
    assert resp.status_code == 200
    assert isinstance(resp.json(), list)


@pytest.mark.asyncio
async def test_sync_requires_admin(client: AsyncClient, unique_email: str) -> None:
    reg = await client.post(
        "/api/v1/auth/register",
        json={"email": unique_email, "password": "S3cure!Passw0rd"},
    )
    token = reg.json()["token"]["access_token"]
    resp = await client.post(
        "/api/v1/marketplaces/kinguin/sync/prices",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403


# ---------------------------------------------------------------------------
# Webhooks
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_webhook_processed_and_idempotent(
    client: AsyncClient, admin_headers: dict[str, str]
) -> None:
    event = {"event_type": "order.completed", "id": "evt-12345"}

    first = await client.post("/api/v1/webhooks/kinguin", json=event)
    assert first.status_code == 200, first.text
    assert first.json()["received"] is True
    assert first.json()["status"] == "processed"

    # Replaying the same external id is de-duplicated, not reprocessed.
    second = await client.post("/api/v1/webhooks/kinguin", json=event)
    assert second.status_code == 200
    assert "Duplicate" in (second.json()["detail"] or "")

    # Audit trail visible to admins.
    events = await client.get(
        "/api/v1/webhook-events?provider=kinguin", headers=admin_headers
    )
    assert events.status_code == 200
    assert any(e["external_id"] == "evt-12345" for e in events.json())


@pytest.mark.asyncio
async def test_webhook_unknown_provider_404(client: AsyncClient) -> None:
    resp = await client.post("/api/v1/webhooks/nosuchprovider", json={"id": "x"})
    assert resp.status_code == 404
