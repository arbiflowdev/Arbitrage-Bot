"""Pytest configuration.

Tests run against a SQLite in-memory database so they don't require a
running PostgreSQL instance for smoke verification. They still exercise
the full ASGI stack, services, repositories, and JWT issuance.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator

# Override settings BEFORE any app modules import the singleton.
os.environ.setdefault("APP_ENV", "test")
os.environ.setdefault("DATABASE_URL", "sqlite+aiosqlite:///:memory:")
os.environ.setdefault("REDIS_URL", "redis://localhost:6379/0")
os.environ.setdefault("JWT_SECRET", "test-secret-must-be-at-least-sixteen-chars")
os.environ.setdefault("LOG_JSON", "false")
os.environ.setdefault("LOG_LEVEL", "WARNING")
# Marketplace integrations: run in mock mode (no API keys needed).
os.environ.setdefault("MARKETPLACE_MODE", "mock")
# Keep the pre-scan listings auto-import OFF by default in tests so suites that
# seed listings directly aren't forced to mock the offer-search endpoint. Tests
# that exercise the auto-import opt in explicitly.
os.environ.setdefault("PRICING_SYNC_LISTINGS_BEFORE_SCAN", "false")

import pytest  # noqa: E402
import pytest_asyncio  # noqa: E402
from httpx import ASGITransport, AsyncClient  # noqa: E402

from app.core.database import engine  # noqa: E402
from app.main import app  # noqa: E402
from app.models.base import Base  # noqa: E402


@pytest_asyncio.fixture(scope="session", autouse=True)
async def _create_schema() -> AsyncIterator[None]:
    """Create tables once per test session against the in-memory DB."""
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
    yield
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)


@pytest_asyncio.fixture
async def client() -> AsyncIterator[AsyncClient]:
    """An ASGI-bound httpx client for hitting the FastAPI app."""
    transport = ASGITransport(app=app)
    async with AsyncClient(transport=transport, base_url="http://test") as ac:
        yield ac


@pytest.fixture
def unique_email() -> str:
    import uuid

    return f"user-{uuid.uuid4().hex[:8]}@example.com"


@pytest_asyncio.fixture
async def admin_headers(client: AsyncClient, unique_email: str) -> dict[str, str]:
    """Register a user, promote it to admin, and return bearer auth headers."""
    from app.core.database import AsyncSessionLocal  # noqa: E402
    from app.models.user import UserRole  # noqa: E402
    from app.repositories.user_repository import UserRepository  # noqa: E402

    password = "S3cure!Passw0rd"
    reg = await client.post(
        "/api/v1/auth/register",
        json={"email": unique_email, "password": password},
    )
    assert reg.status_code == 201, reg.text

    async with AsyncSessionLocal() as session:
        repo = UserRepository(session)
        user = await repo.get_by_email(unique_email.lower())
        assert user is not None
        user.role = UserRole.ADMIN
        await session.commit()

    login = await client.post(
        "/api/v1/auth/login",
        json={"email": unique_email, "password": password},
    )
    token = login.json()["access_token"]
    return {"Authorization": f"Bearer {token}"}
