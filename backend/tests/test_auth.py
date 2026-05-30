"""Smoke tests for the authentication flow."""

from __future__ import annotations

import pytest
from httpx import AsyncClient


@pytest.mark.asyncio
async def test_register_then_login_then_me(
    client: AsyncClient, unique_email: str
) -> None:
    password = "S3cure!Passw0rd"

    # Register
    resp = await client.post(
        "/api/v1/auth/register",
        json={
            "email": unique_email,
            "password": password,
            "full_name": "Smoke Test",
        },
    )
    assert resp.status_code == 201, resp.text
    body = resp.json()
    assert body["user"]["email"] == unique_email
    assert body["user"]["role"] == "user"
    assert body["token"]["token_type"] == "bearer"
    assert body["token"]["access_token"]

    # Login
    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": unique_email, "password": password},
    )
    assert resp.status_code == 200, resp.text
    token = resp.json()["access_token"]

    # Me
    resp = await client.get(
        "/api/v1/auth/me",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 200, resp.text
    me = resp.json()
    assert me["email"] == unique_email
    assert me["is_active"] is True


@pytest.mark.asyncio
async def test_duplicate_register_returns_409(
    client: AsyncClient, unique_email: str
) -> None:
    payload = {"email": unique_email, "password": "S3cure!Passw0rd"}

    first = await client.post("/api/v1/auth/register", json=payload)
    assert first.status_code == 201

    second = await client.post("/api/v1/auth/register", json=payload)
    assert second.status_code == 409


@pytest.mark.asyncio
async def test_login_with_wrong_password_returns_401(
    client: AsyncClient, unique_email: str
) -> None:
    await client.post(
        "/api/v1/auth/register",
        json={"email": unique_email, "password": "S3cure!Passw0rd"},
    )
    resp = await client.post(
        "/api/v1/auth/login",
        json={"email": unique_email, "password": "wrong-password"},
    )
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_me_without_token_returns_401(client: AsyncClient) -> None:
    resp = await client.get("/api/v1/auth/me")
    assert resp.status_code == 401


@pytest.mark.asyncio
async def test_settings_requires_admin(
    client: AsyncClient, unique_email: str
) -> None:
    # Regular user receives 403 on the admin-only endpoint.
    password = "S3cure!Passw0rd"
    reg = await client.post(
        "/api/v1/auth/register",
        json={"email": unique_email, "password": password},
    )
    token = reg.json()["token"]["access_token"]

    resp = await client.get(
        "/api/v1/settings",
        headers={"Authorization": f"Bearer {token}"},
    )
    assert resp.status_code == 403
