"""Kinguin marketplace adapter.

Targets the Kinguin ESA (eCommerce Sales API), base
``https://gateway.kinguin.net/esa/api`` with ``X-Api-Key`` authentication.

NOTE: exact endpoint paths/field names follow Kinguin's documented ESA API and
should be re-verified against current docs once live API access is granted.
The adapter is dormant until an active credential is configured, so it is safe
to ship without keys.
"""

from __future__ import annotations

import hashlib
import hmac
from typing import Any

from app.core.logging import get_logger
from app.integrations.base import (
    MarketplaceAdapter,
    NormalizedListing,
    NormalizedOrder,
    NormalizedPrice,
    NormalizedProduct,
    ParsedWebhook,
    to_decimal,
)

log = get_logger(__name__)


class KinguinAdapter(MarketplaceAdapter):
    provider = "kinguin"

    def _auth_headers(self) -> dict[str, str]:
        creds = self._require_credentials()
        return {"X-Api-Key": creds.api_key or "", "Accept": "application/json"}

    @staticmethod
    def _items(data: Any) -> list[dict[str, Any]]:
        """Extract a list of records from Kinguin's paginated envelope."""
        if isinstance(data, dict):
            results = data.get("results", data.get("data", []))
            return [r for r in results if isinstance(r, dict)]
        if isinstance(data, list):
            return [r for r in data if isinstance(r, dict)]
        return []

    @staticmethod
    def _sku_of(item: dict[str, Any]) -> str:
        return str(
            item.get("productId")
            or item.get("kinguinId")
            or item.get("id")
            or ""
        )

    def _to_product(self, item: dict[str, Any]) -> NormalizedProduct:
        return NormalizedProduct(
            marketplace_sku=self._sku_of(item),
            name=str(item.get("name", "")),
            price=to_decimal(item.get("price")),
            currency=str(item.get("currency", "EUR")),
            available_qty=item.get("qty"),
            region=item.get("regionalLimitations") or item.get("region"),
            platform=item.get("platform"),
            raw=item,
        )

    async def fetch_products(
        self, *, limit: int = 50, page: int = 1
    ) -> list[NormalizedProduct]:
        data = await self.http.request_json(
            "GET",
            "/v1/products",
            params={"limit": limit, "page": page},
            headers=self._auth_headers(),
        )
        return [self._to_product(item) for item in self._items(data)]

    async def fetch_prices(
        self, skus: list[str] | None = None
    ) -> list[NormalizedPrice]:
        data = await self.http.request_json(
            "GET",
            "/v1/products",
            params={"limit": 100, "page": 1},
            headers=self._auth_headers(),
        )
        wanted = set(skus) if skus else None
        prices: list[NormalizedPrice] = []
        for item in self._items(data):
            sku = self._sku_of(item)
            if wanted is not None and sku not in wanted:
                continue
            price = to_decimal(item.get("price"))
            if price is None:
                continue
            qty = item.get("qty")
            prices.append(
                NormalizedPrice(
                    marketplace_sku=sku,
                    price=price,
                    currency=str(item.get("currency", "EUR")),
                    available_qty=qty,
                    is_available=bool(qty) if qty is not None else True,
                    raw=item,
                )
            )
        return prices

    async def fetch_listings(self) -> list[NormalizedListing]:
        # Kinguin is primarily a sourcing marketplace; seller listings are
        # managed under the merchant API. Returning [] keeps the unified
        # interface honest until merchant-listing access is configured.
        log.info("kinguin.fetch_listings.noop", provider=self.provider)
        self._require_credentials()
        return []

    async def fetch_orders(
        self, *, limit: int = 50, page: int = 1
    ) -> list[NormalizedOrder]:
        data = await self.http.request_json(
            "GET",
            "/v1/order",
            params={"limit": limit, "page": page},
            headers=self._auth_headers(),
        )
        orders: list[NormalizedOrder] = []
        for item in self._items(data):
            orders.append(
                NormalizedOrder(
                    external_order_id=str(item.get("orderId") or item.get("id") or ""),
                    marketplace_sku=self._sku_of(item),
                    quantity=int(item.get("qty", 1) or 1),
                    total=to_decimal(item.get("totalPrice") or item.get("price")),
                    currency=str(item.get("currency", "EUR")),
                    status=str(item.get("status", "unknown")),
                    raw=item,
                )
            )
        return orders

    async def push_listing(self, listing: NormalizedListing) -> NormalizedListing:
        payload = {
            "price": str(listing.price) if listing.price is not None else None,
            "qty": listing.stock,
        }
        data = await self.http.request_json(
            "PATCH",
            f"/v1/products/{listing.marketplace_sku}",
            json=payload,
            headers=self._auth_headers(),
        )
        item = data if isinstance(data, dict) else {}
        return NormalizedListing(
            marketplace_sku=listing.marketplace_sku,
            external_listing_id=str(item.get("id"))
            if item.get("id") is not None
            else listing.external_listing_id,
            title=listing.title,
            price=listing.price,
            currency=listing.currency,
            stock=listing.stock,
            status="synced",
            raw=item,
        )

    async def health_check(self) -> bool:
        # A cheap authenticated call; any 2xx means the key works.
        await self.http.request_json(
            "GET",
            "/v1/products",
            params={"limit": 1, "page": 1},
            headers=self._auth_headers(),
        )
        return True

    def verify_webhook(self, headers: dict[str, str], body: bytes) -> bool:
        secret = (self.credentials.api_secret if self.credentials else None) or ""
        signature = headers.get("x-event-secret") or headers.get("X-Event-Secret")
        if not secret or not signature:
            return False
        expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, signature)

    def parse_webhook(
        self, headers: dict[str, str], payload: dict[str, Any]
    ) -> ParsedWebhook:
        return ParsedWebhook(
            event_type=str(payload.get("type") or payload.get("event") or "unknown"),
            external_id=(
                str(payload["id"]) if payload.get("id") is not None else None
            ),
            data=payload,
        )
