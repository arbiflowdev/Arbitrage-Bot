"""G2G marketplace adapter.

Targets the G2G open API, base ``https://open.g2g.com``. G2G authenticates
with an API key plus a secret used to sign requests.

NOTE: exact endpoint paths/field names follow G2G's documented API and should
be re-verified against current docs once live API access is granted. The
adapter stays dormant until an active credential is configured.
"""

from __future__ import annotations

import hashlib
import hmac
from typing import Any

from app.integrations.base import (
    MarketplaceAdapter,
    NormalizedListing,
    NormalizedOrder,
    NormalizedPrice,
    NormalizedProduct,
    ParsedWebhook,
    to_decimal,
)


class G2GAdapter(MarketplaceAdapter):
    provider = "g2g"

    def _auth_headers(self) -> dict[str, str]:
        creds = self._require_credentials()
        return {
            "g2g-api-key": creds.api_key or "",
            "Accept": "application/json",
        }

    @staticmethod
    def _items(data: Any) -> list[dict[str, Any]]:
        if isinstance(data, dict):
            payload = data.get("payload", data)
            if isinstance(payload, dict):
                results = payload.get("results", payload.get("data", []))
            else:
                results = payload
            return [r for r in (results or []) if isinstance(r, dict)]
        if isinstance(data, list):
            return [r for r in data if isinstance(r, dict)]
        return []

    @staticmethod
    def _sku_of(item: dict[str, Any]) -> str:
        return str(
            item.get("offer_id")
            or item.get("product_id")
            or item.get("relation_id")
            or item.get("id")
            or ""
        )

    def _to_product(self, item: dict[str, Any]) -> NormalizedProduct:
        return NormalizedProduct(
            marketplace_sku=self._sku_of(item),
            name=str(item.get("title") or item.get("offer_title") or ""),
            price=to_decimal(item.get("unit_price") or item.get("price")),
            currency=str(item.get("currency", "USD")),
            available_qty=item.get("available_stock") or item.get("qty"),
            region=item.get("region"),
            platform=item.get("brand") or item.get("platform"),
            raw=item,
        )

    async def fetch_products(
        self, *, limit: int = 50, page: int = 1
    ) -> list[NormalizedProduct]:
        data = await self.http.request_json(
            "GET",
            "/v1/offers",
            params={"page_size": limit, "page": page},
            headers=self._auth_headers(),
        )
        return [self._to_product(item) for item in self._items(data)]

    async def fetch_prices(
        self, skus: list[str] | None = None
    ) -> list[NormalizedPrice]:
        data = await self.http.request_json(
            "GET",
            "/v1/offers",
            params={"page_size": 100, "page": 1},
            headers=self._auth_headers(),
        )
        wanted = set(skus) if skus else None
        prices: list[NormalizedPrice] = []
        for item in self._items(data):
            sku = self._sku_of(item)
            if wanted is not None and sku not in wanted:
                continue
            price = to_decimal(item.get("unit_price") or item.get("price"))
            if price is None:
                continue
            qty = item.get("available_stock") or item.get("qty")
            prices.append(
                NormalizedPrice(
                    marketplace_sku=sku,
                    price=price,
                    currency=str(item.get("currency", "USD")),
                    available_qty=qty,
                    is_available=bool(qty) if qty is not None else True,
                    raw=item,
                )
            )
        return prices

    async def fetch_listings(self) -> list[NormalizedListing]:
        data = await self.http.request_json(
            "GET",
            "/v1/offers",
            params={"page_size": 100, "page": 1, "seller": "self"},
            headers=self._auth_headers(),
        )
        listings: list[NormalizedListing] = []
        for item in self._items(data):
            listings.append(
                NormalizedListing(
                    marketplace_sku=self._sku_of(item),
                    external_listing_id=str(item.get("offer_id"))
                    if item.get("offer_id") is not None
                    else None,
                    title=item.get("title") or item.get("offer_title"),
                    price=to_decimal(item.get("unit_price") or item.get("price")),
                    currency=str(item.get("currency", "USD")),
                    stock=int(item.get("available_stock") or 0),
                    status=str(item.get("status", "active")),
                    raw=item,
                )
            )
        return listings

    async def fetch_orders(
        self, *, limit: int = 50, page: int = 1
    ) -> list[NormalizedOrder]:
        data = await self.http.request_json(
            "GET",
            "/v1/orders",
            params={"page_size": limit, "page": page},
            headers=self._auth_headers(),
        )
        orders: list[NormalizedOrder] = []
        for item in self._items(data):
            orders.append(
                NormalizedOrder(
                    external_order_id=str(item.get("order_id") or item.get("id") or ""),
                    marketplace_sku=self._sku_of(item),
                    quantity=int(item.get("quantity", 1) or 1),
                    total=to_decimal(item.get("amount") or item.get("total")),
                    currency=str(item.get("currency", "USD")),
                    status=str(item.get("status", "unknown")),
                    raw=item,
                )
            )
        return orders

    async def push_listing(self, listing: NormalizedListing) -> NormalizedListing:
        payload = {
            "unit_price": str(listing.price) if listing.price is not None else None,
            "available_stock": listing.stock,
        }
        if listing.external_listing_id:
            data = await self.http.request_json(
                "PUT",
                f"/v1/offers/{listing.external_listing_id}",
                json=payload,
                headers=self._auth_headers(),
            )
        else:
            payload["title"] = listing.title
            data = await self.http.request_json(
                "POST",
                "/v1/offers",
                json=payload,
                headers=self._auth_headers(),
            )
        item = data.get("payload", data) if isinstance(data, dict) else {}
        if not isinstance(item, dict):
            item = {}
        return NormalizedListing(
            marketplace_sku=listing.marketplace_sku,
            external_listing_id=str(item.get("offer_id"))
            if item.get("offer_id") is not None
            else listing.external_listing_id,
            title=listing.title,
            price=listing.price,
            currency=listing.currency,
            stock=listing.stock,
            status="synced",
            raw=item,
        )

    async def health_check(self) -> bool:
        await self.http.request_json(
            "GET",
            "/v1/offers",
            params={"page_size": 1, "page": 1},
            headers=self._auth_headers(),
        )
        return True

    def verify_webhook(self, headers: dict[str, str], body: bytes) -> bool:
        secret = (self.credentials.api_secret if self.credentials else None) or ""
        signature = headers.get("g2g-signature") or headers.get("G2G-Signature")
        if not secret or not signature:
            return False
        expected = hmac.new(secret.encode(), body, hashlib.sha256).hexdigest()
        return hmac.compare_digest(expected, signature)

    def parse_webhook(
        self, headers: dict[str, str], payload: dict[str, Any]
    ) -> ParsedWebhook:
        return ParsedWebhook(
            event_type=str(payload.get("event_type") or payload.get("type") or "unknown"),
            external_id=(
                str(payload["id"]) if payload.get("id") is not None else None
            ),
            data=payload,
        )
