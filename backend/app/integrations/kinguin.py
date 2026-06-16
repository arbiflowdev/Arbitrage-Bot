"""Kinguin marketplace adapter.

Targets the Kinguin ESA (eCommerce Sales API), base
``https://gateway.kinguin.net/esa/api`` with ``X-Api-Key`` authentication.

NOTE: exact endpoint paths/field names follow Kinguin's documented ESA API and
should be re-verified against current docs once live API access is granted.
The adapter is dormant until an active credential is configured, so it is safe
to ship without keys.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
from typing import Any

from app.core.logging import get_logger
from app.integrations.base import (
    DeliveryResult,
    MarketplaceAdapter,
    NormalizedListing,
    NormalizedOrder,
    NormalizedPrice,
    NormalizedProduct,
    ParsedWebhook,
    PurchaseResult,
    to_decimal,
)
from app.integrations.exceptions import ProviderAPIError

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

    # ------------------------------------------------------------------
    # Fulfillment — Kinguin is a BUY/source marketplace
    # ------------------------------------------------------------------
    #: Bounded poll for key release after an order is placed.
    _KEYS_POLL_ATTEMPTS = 6
    _KEYS_POLL_DELAY_SECONDS = 1.5

    async def purchase(
        self,
        marketplace_sku: str,
        *,
        quantity: int = 1,
        idempotency_key: str | None = None,
    ) -> PurchaseResult:
        """Buy ``quantity`` of a product from Kinguin and return the code.

        Flow (Kinguin ESA — docs: github.com/kinguinltdhk/Kinguin-eCommerce-API):
          1. GET /v2/products/{id} for the current price (Kinguin orders carry
             the max price the buyer accepts).
          2. POST /v2/order {products:[{productId, qty, price}]} -> orderId.
          3. Poll GET /v2/order/{orderId}/keys until the serial(s) are released.
        NOTE: the keys-response field name (serial/key/code) should be confirmed
        against live data; ``_extract_keys`` parses the common shapes defensively.
        """
        headers = self._auth_headers()
        product = await self.http.request_json(
            "GET", f"/v2/products/{marketplace_sku}", headers=headers
        )
        price = to_decimal(product.get("price")) if isinstance(product, dict) else None
        currency = (
            str(product.get("currency", "EUR")) if isinstance(product, dict) else "EUR"
        )
        if price is None:
            raise ProviderAPIError(
                f"Kinguin product '{marketplace_sku}' has no price; cannot purchase."
            )

        order_body: dict[str, Any] = {
            "products": [
                {"productId": marketplace_sku, "qty": quantity, "price": float(price)}
            ]
        }
        if idempotency_key:
            order_body["orderExternalId"] = idempotency_key
        created = await self.http.request_json(
            "POST",
            "/v2/order",
            json=order_body,
            headers={**headers, "Content-Type": "application/json"},
        )
        order_id = str(created.get("orderId")) if isinstance(created, dict) else ""
        if not order_id:
            raise ProviderAPIError(
                f"Kinguin order creation returned no orderId: {created!r}"
            )

        codes: list[str] = []
        for attempt in range(self._KEYS_POLL_ATTEMPTS):
            data = await self.http.request_json(
                "GET", f"/v2/order/{order_id}/keys", headers=headers
            )
            codes = self._extract_keys(data)
            if codes:
                break
            if attempt < self._KEYS_POLL_ATTEMPTS - 1:
                await asyncio.sleep(self._KEYS_POLL_DELAY_SECONDS)
        if not codes:
            raise ProviderAPIError(
                f"Kinguin order '{order_id}' produced no keys after polling."
            )

        return PurchaseResult(
            external_purchase_id=order_id,
            code=codes[0],
            cost=price,
            currency=currency,
            raw={"order": created, "keys_count": len(codes)},
        )

    @staticmethod
    def _extract_keys(data: Any) -> list[str]:
        """Pull serial strings from Kinguin's order-keys response (defensive)."""
        items: Any = data
        if isinstance(data, dict):
            items = data.get("results") or data.get("keys") or data.get("data") or []
        if not isinstance(items, list):
            return []
        out: list[str] = []
        for it in items:
            if isinstance(it, str):
                out.append(it)
            elif isinstance(it, dict):
                val = it.get("serial") or it.get("key") or it.get("code") or it.get("value")
                if val:
                    out.append(str(val))
        return out

    async def deliver(
        self,
        external_order_id: str,
        code: str,
        *,
        marketplace_sku: str | None = None,
    ) -> DeliveryResult:
        # Selling/delivering ON Kinguin uses Kinguin's separate Merchant API, not
        # the ESA buying API wired here. Kinguin is configured as a source only.
        raise NotImplementedError(
            "Delivery on Kinguin requires the Kinguin Merchant API (not the ESA "
            "buying API). Kinguin is wired as a source/buy marketplace only."
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
