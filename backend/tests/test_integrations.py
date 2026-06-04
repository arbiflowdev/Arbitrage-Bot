"""Tests for the integration layer: HTTP client, mock + real adapters."""

from __future__ import annotations

from decimal import Decimal

import httpx
import pytest
import respx

from app.integrations.base import ProviderCredentials
from app.integrations.exceptions import (
    CredentialsNotConfigured,
    ProviderAPIError,
    ProviderUnavailable,
)
from app.integrations.eneba import EnebaAdapter
from app.integrations.http import MarketplaceHTTPClient
from app.integrations.kinguin import KinguinAdapter
from app.integrations.mock import MockAdapter
from app.integrations.registry import build_adapter, is_supported


# ---------------------------------------------------------------------------
# HTTP client
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_http_retries_then_succeeds() -> None:
    client = MarketplaceHTTPClient("t", "https://api.test", max_retries=3, backoff=0.0)
    with respx.mock:
        route = respx.get("https://api.test/ping").mock(
            side_effect=[
                httpx.Response(500),
                httpx.Response(200, json={"ok": True}),
            ]
        )
        data = await client.request_json("GET", "/ping")
    assert data == {"ok": True}
    assert route.call_count == 2
    await client.aclose()


@pytest.mark.asyncio
async def test_http_persistent_5xx_raises_provider_api_error() -> None:
    client = MarketplaceHTTPClient("t", "https://api.test", max_retries=1, backoff=0.0)
    with respx.mock:
        respx.get("https://api.test/x").mock(return_value=httpx.Response(503))
        with pytest.raises(ProviderAPIError):
            await client.request_json("GET", "/x")
    await client.aclose()


@pytest.mark.asyncio
async def test_http_network_error_raises_provider_unavailable() -> None:
    client = MarketplaceHTTPClient("t", "https://api.test", max_retries=1, backoff=0.0)

    def boom(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("down", request=request)

    with respx.mock:
        respx.get("https://api.test/y").mock(side_effect=boom)
        with pytest.raises(ProviderUnavailable):
            await client.request_json("GET", "/y")
    await client.aclose()


# ---------------------------------------------------------------------------
# Mock adapter
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_mock_adapter_is_deterministic() -> None:
    a = MockAdapter(provider="kinguin")
    prices1 = await a.fetch_prices(["KINGUIN-SKU-0001"])
    prices2 = await a.fetch_prices(["KINGUIN-SKU-0001"])
    assert prices1[0].price == prices2[0].price
    assert isinstance(prices1[0].price, Decimal)


@pytest.mark.asyncio
async def test_mock_adapter_needs_no_credentials() -> None:
    a = MockAdapter(provider="g2g")
    products = await a.fetch_products(limit=5)
    assert len(products) > 0
    assert await a.health_check() is True


# ---------------------------------------------------------------------------
# Kinguin adapter (real HTTP shape, mocked transport)
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_kinguin_fetch_products_parses_envelope() -> None:
    http = MarketplaceHTTPClient(
        "kinguin", "https://gw.test", max_retries=0, backoff=0.0
    )
    adapter = KinguinAdapter(
        credentials=ProviderCredentials(api_key="key123"), http=http
    )
    with respx.mock:
        respx.get("https://gw.test/v1/products").mock(
            return_value=httpx.Response(
                200,
                json={
                    "results": [
                        {
                            "productId": "PID-1",
                            "name": "Game A",
                            "price": "12.50",
                            "qty": 7,
                            "currency": "EUR",
                        }
                    ]
                },
            )
        )
        products = await adapter.fetch_products()
    assert len(products) == 1
    assert products[0].marketplace_sku == "PID-1"
    assert products[0].price == Decimal("12.50")
    await adapter.aclose()


@pytest.mark.asyncio
async def test_kinguin_dormant_without_credentials() -> None:
    http = MarketplaceHTTPClient("kinguin", "https://gw.test")
    adapter = KinguinAdapter(credentials=None, http=http)
    with pytest.raises(CredentialsNotConfigured):
        await adapter.fetch_products()
    await adapter.aclose()


# ---------------------------------------------------------------------------
# Eneba adapter (OAuth 2.0 + GraphQL, mocked transport)
# ---------------------------------------------------------------------------
@pytest.mark.asyncio
async def test_eneba_oauth_then_graphql_fetch_prices() -> None:
    http = MarketplaceHTTPClient(
        "eneba", "https://api.eneba.com", max_retries=0, backoff=0.0
    )
    adapter = EnebaAdapter(
        credentials=ProviderCredentials(
            api_key="client-id",
            api_secret="auth-secret",
            extra={"auth_id": "auth-id", "webhook_secret": "wh-secret"},
        ),
        http=http,
    )
    with respx.mock:
        token_route = respx.post("https://user.eneba.com/oauth/token").mock(
            return_value=httpx.Response(
                200,
                json={"access_token": "tok-abc", "expires_in": 3600, "token_type": "Bearer"},
            )
        )
        respx.post("https://api.eneba.com/graphql/").mock(
            return_value=httpx.Response(
                200,
                json={
                    "data": {
                        "S_stock": {
                            "edges": [
                                {
                                    "node": {
                                        "id": "auction-1",
                                        "product": {"id": "PROD-1"},
                                        "price": {"amount": 1099, "currency": "EUR"},
                                        "availableStock": 5,
                                    }
                                }
                            ]
                        }
                    }
                },
            )
        )
        prices = await adapter.fetch_prices()
    assert token_route.called
    assert len(prices) == 1
    assert prices[0].marketplace_sku == "PROD-1"
    assert prices[0].price == Decimal("10.99")  # minor units (1099) -> major
    assert prices[0].available_qty == 5
    await adapter.aclose()


@pytest.mark.asyncio
async def test_eneba_dormant_without_credentials() -> None:
    http = MarketplaceHTTPClient("eneba", "https://api.eneba.com")
    adapter = EnebaAdapter(credentials=None, http=http)
    with pytest.raises(CredentialsNotConfigured):
        await adapter.fetch_prices()
    await adapter.aclose()


def test_eneba_webhook_signature_header() -> None:
    adapter = EnebaAdapter(
        credentials=ProviderCredentials(
            api_key="client-id", extra={"webhook_secret": "shared-secret"}
        )
    )
    assert adapter.verify_webhook({"authorization": "shared-secret"}, b"{}") is True
    assert adapter.verify_webhook({"authorization": "wrong"}, b"{}") is False
    assert adapter.verify_webhook({}, b"{}") is False


# ---------------------------------------------------------------------------
# Registry
# ---------------------------------------------------------------------------
def test_registry_supported_providers() -> None:
    assert is_supported("kinguin")
    assert is_supported("g2g")
    assert is_supported("eneba")
    assert not is_supported("nope")


def test_registry_mock_mode_returns_mock_adapter() -> None:
    adapter = build_adapter("kinguin", None, mode="mock")
    assert isinstance(adapter, MockAdapter)
    assert adapter.provider == "kinguin"


def test_registry_unknown_provider_raises() -> None:
    with pytest.raises(ValueError):
        build_adapter("nope", None)


# ---------------------------------------------------------------------------
# .env credential fallback
# ---------------------------------------------------------------------------
def test_env_credentials_fallback() -> None:
    from app.core.config import Settings

    s = Settings(
        KINGUIN_API_KEY="k-live",
        KINGUIN_API_SECRET="k-secret",
        G2G_API_KEY="",
    )
    assert s.env_credentials_for("kinguin") == {
        "api_key": "k-live",
        "api_secret": "k-secret",
    }
    # Blank/missing key → no fallback (DB store / mock mode stays in control).
    assert s.env_credentials_for("g2g") is None
    assert s.env_credentials_for("unknown") is None


def test_env_credentials_fallback_eneba() -> None:
    from app.core.config import Settings

    # Eneba carries OAuth values + webhook secret under "extra".
    s = Settings(
        ENEBA_CLIENT_ID="cid",
        ENEBA_AUTH_ID="aid",
        ENEBA_API_SECRET="sec",
        ENEBA_WEBHOOK_SECRET="wh",
    )
    assert s.env_credentials_for("eneba") == {
        "api_key": "cid",
        "api_secret": "sec",
        "extra": {"auth_id": "aid", "webhook_secret": "wh"},
    }
    # No client id → dormant.
    assert Settings(ENEBA_CLIENT_ID="").env_credentials_for("eneba") is None
