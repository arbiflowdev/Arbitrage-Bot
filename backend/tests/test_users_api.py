"""API tests for the Milestone 5 user-management endpoints (admin only)."""

from __future__ import annotations

import uuid

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_users_requires_admin(client: AsyncClient) -> None:
    assert (await client.get("/api/v1/users")).status_code == 401


@pytest.mark.asyncio
async def test_admin_creates_lists_and_manages_users(
    client: AsyncClient, admin_headers: dict[str, str]
) -> None:
    email = f"newadmin-{uuid.uuid4().hex[:8]}@example.com"

    created = await client.post(
        "/api/v1/users",
        headers=admin_headers,
        json={"email": email, "password": "S3cure!pass", "role": "admin"},
    )
    assert created.status_code == 201, created.text
    uid = created.json()["id"]
    assert created.json()["role"] == "admin"

    listing = await client.get("/api/v1/users", headers=admin_headers)
    assert listing.status_code == 200
    assert any(u["id"] == uid for u in listing.json())

    demote = await client.patch(
        f"/api/v1/users/{uid}", headers=admin_headers, json={"role": "user"}
    )
    assert demote.status_code == 200
    assert demote.json()["role"] == "user"

    deactivate = await client.patch(
        f"/api/v1/users/{uid}", headers=admin_headers, json={"is_active": False}
    )
    assert deactivate.status_code == 200
    assert deactivate.json()["is_active"] is False

    duplicate = await client.post(
        "/api/v1/users",
        headers=admin_headers,
        json={"email": email, "password": "S3cure!pass"},
    )
    assert duplicate.status_code == 409
