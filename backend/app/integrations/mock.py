"""Deterministic mock adapter.

Used when ``MARKETPLACE_MODE=mock`` (the default) so the whole platform can be
exercised end-to-end without any real API keys. Output is deterministic — the
same SKU always yields the same price — so tests and demos are reproducible.
It can impersonate any provider name, letting mock mode stand in for Kinguin,
G2G, etc.
"""

from __future__ import annotations

import hashlib
from decimal import Decimal
from typing import Any

from app.integrations.base import (
    MarketplaceAdapter,
    NormalizedListing,
    NormalizedOrder,
    NormalizedPrice,
    NormalizedProduct,
    ParsedWebhook,
    ProviderCredentials,
)
from app.integrations.http import MarketplaceHTTPClient


class MockAdapter(MarketplaceAdapter):
    """A credential-free, deterministic stand-in for a real marketplace."""

    provider = "mock"

    def __init__(
        self,
        provider: str = "mock",
        credentials: ProviderCredentials | None = None,
        http: MarketplaceHTTPClient | None = None,
    ) -> None:
        super().__init__(credentials, http)
        self.provider = provider

    def _deterministic_price(self, marketplace_sku: str) -> Decimal:
        digest = hashlib.sha256(f"{self.provider}:{marketplace_sku}".encode())
        cents = int(digest.hexdigest(), 16) % 5000 + 100  # 1.00 .. 51.00
        return Decimal(cents) / Decimal(100)

    def _sku(self, index: int) -> str:
        return f"{self.provider.upper()}-SKU-{index:04d}"

    async def fetch_products(
        self, *, limit: int = 50, page: int = 1
    ) -> list[NormalizedProduct]:
        start = (page - 1) * limit
        return [
            NormalizedProduct(
                marketplace_sku=self._sku(start + i),
                name=f"Mock Digital Good {start + i}",
                price=self._deterministic_price(self._sku(start + i)),
                currency="EUR",
                available_qty=100,
                region="EU",
                platform="Steam",
                raw={"mock": True, "index": start + i},
            )
            for i in range(min(limit, 10))
        ]

    async def fetch_prices(
        self, skus: list[str] | None = None
    ) -> list[NormalizedPrice]:
        target = skus if skus else [self._sku(i) for i in range(10)]
        return [
            NormalizedPrice(
                marketplace_sku=sku,
                price=self._deterministic_price(sku),
                currency="EUR",
                available_qty=100,
                is_available=True,
                raw={"mock": True},
            )
            for sku in target
        ]

    async def fetch_listings(self) -> list[NormalizedListing]:
        return [
            NormalizedListing(
                marketplace_sku=self._sku(i),
                external_listing_id=f"mock-listing-{i}",
                title=f"Mock Listing {i}",
                price=self._deterministic_price(self._sku(i)),
                currency="EUR",
                stock=100,
                status="active",
                raw={"mock": True},
            )
            for i in range(5)
        ]

    async def fetch_orders(
        self, *, limit: int = 50, page: int = 1
    ) -> list[NormalizedOrder]:
        return [
            NormalizedOrder(
                external_order_id=f"mock-order-{i}",
                marketplace_sku=self._sku(i),
                quantity=1,
                total=self._deterministic_price(self._sku(i)),
                currency="EUR",
                status="completed",
                raw={"mock": True},
            )
            for i in range(min(limit, 3))
        ]

    async def push_listing(self, listing: NormalizedListing) -> NormalizedListing:
        # Echo back as if the marketplace accepted it, assigning an external id.
        return NormalizedListing(
            marketplace_sku=listing.marketplace_sku,
            external_listing_id=listing.external_listing_id
            or f"mock-listing-{listing.marketplace_sku}",
            title=listing.title,
            price=listing.price,
            currency=listing.currency,
            stock=listing.stock,
            status="active",
            raw={"mock": True, "accepted": True},
        )

    async def health_check(self) -> bool:
        return True

    def verify_webhook(self, headers: dict[str, str], body: bytes) -> bool:
        # Mock provider trusts everything; real adapters verify signatures.
        return True

    def parse_webhook(
        self, headers: dict[str, str], payload: dict[str, Any]
    ) -> ParsedWebhook:
        return ParsedWebhook(
            event_type=str(payload.get("event_type", "mock.event")),
            external_id=(
                str(payload["id"]) if payload.get("id") is not None else None
            ),
            signature_valid=True,
            data=payload,
        )
