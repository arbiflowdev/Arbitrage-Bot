"""G2G marketplace adapter.

Targets the G2G OpenAPI, base ``https://open-api.g2g.com``. Every request is
signed: headers ``g2g-api-key``, ``g2g-userid``, ``g2g-timestamp`` (ms) and
``g2g-signature`` = HMAC-SHA256(path + api_key + user_id + timestamp, secret).

G2G is wired as a SELL/deliver destination: :meth:`deliver` posts codes to
``/v2/orders/{id}/delivery``. The OpenAPI is seller-side and exposes no buy
endpoint, so :meth:`purchase` is unsupported (source via Kinguin instead). The
OpenAPI officially supports Gift Card & Top Up products.

NOTE: the read/sync methods (fetch_*) still use the older ``/v1/offers`` paths
and unsigned headers and must be updated to the signed v2 product endpoints
before live price-sync; the buy/deliver path is the focus of live fulfillment.
The adapter stays dormant until an active credential is configured.
"""

from __future__ import annotations

import hashlib
import hmac
import time
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


class G2GAdapter(MarketplaceAdapter):
    provider = "g2g"

    def _auth_headers(self) -> dict[str, str]:
        creds = self._require_credentials()
        return {
            "g2g-api-key": creds.api_key or "",
            "Accept": "application/json",
        }

    def _signed_headers(
        self, canonical_path: str, *, json_body: bool = False
    ) -> dict[str, str]:
        """Build G2G OpenAPI signed-request headers.

        Per docs.g2g.com "Verifying Signatures":
            canonical = path + api_key + user_id + timestamp_ms
            g2g-signature = HMAC_SHA256(canonical, api_secret).hexdigest()
        ``canonical_path`` is the request path WITHOUT query string (matching the
        documented worked example). Timestamp is milliseconds since epoch.
        """
        creds = self._require_credentials()
        api_key = creds.api_key or ""
        secret = (creds.api_secret or "").encode("utf-8")
        user_id = str((creds.extra or {}).get("user_id") or "")
        timestamp = str(int(time.time() * 1000))
        canonical = f"{canonical_path}{api_key}{user_id}{timestamp}".encode()
        signature = hmac.new(secret, canonical, hashlib.sha256).hexdigest()
        headers = {
            "g2g-api-key": api_key,
            "g2g-userid": user_id,
            "g2g-timestamp": timestamp,
            "g2g-signature": signature,
            "Accept": "application/json",
        }
        if json_body:
            headers["Content-Type"] = "application/json"
        return headers

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

    # ------------------------------------------------------------------
    # Fulfillment — G2G is a SELL/deliver destination
    # ------------------------------------------------------------------
    async def deliver(
        self,
        external_order_id: str,
        code: str,
        *,
        marketplace_sku: str | None = None,
    ) -> DeliveryResult:
        """Deliver a digital code to a buyer's G2G order.

        Flow (docs.g2g.com): GET the order's pending delivery to obtain the
        ``delivery_id``, then POST the code(s) to
        ``/v2/orders/{order_id}/delivery``. A success carries ``code 20000001``.
        NOTE: the G2G OpenAPI officially supports Gift Card & Top Up products.
        """
        path = f"/v2/orders/{external_order_id}/delivery"
        info = await self.http.request_json(
            "GET", path, headers=self._signed_headers(path)
        )
        payload = info.get("payload") if isinstance(info, dict) else None
        delivery_list = (payload or {}).get("delivery_list") or []
        delivery_id: str | None = None
        for entry in delivery_list:
            summary = entry.get("delivery_summary") if isinstance(entry, dict) else None
            if not isinstance(summary, dict) or not summary.get("delivery_id"):
                continue
            # Prefer a delivery still awaiting codes.
            if (entry.get("undelivered_qty") or 0) > 0 or summary.get(
                "delivery_status"
            ) in ("in progress", "pending"):
                delivery_id = str(summary["delivery_id"])
                break
            delivery_id = delivery_id or str(summary["delivery_id"])
        if not delivery_id:
            raise ProviderAPIError(
                f"No pending G2G delivery found for order '{external_order_id}'."
            )

        body = {
            "delivery_id": delivery_id,
            "codes": [
                {
                    "content": code,
                    "content_type": "text/plain",
                    "reference_id": marketplace_sku or external_order_id,
                }
            ],
        }
        resp = await self.http.request_json(
            "POST", path, json=body, headers=self._signed_headers(path, json_body=True)
        )
        success = isinstance(resp, dict) and str(resp.get("code")) == "20000001"
        ref = (resp.get("payload") or {}).get("delivery_id") if isinstance(resp, dict) else None
        return DeliveryResult(
            success=success,
            reference=str(ref or delivery_id),
            raw=resp if isinstance(resp, dict) else {},
        )

    async def purchase(
        self,
        marketplace_sku: str,
        *,
        quantity: int = 1,
        idempotency_key: str | None = None,
    ) -> PurchaseResult:
        # The G2G OpenAPI is seller-side (create offer / upload code / deliver)
        # and exposes NO buy endpoint, so JIT sourcing FROM G2G is not possible.
        # Source purchases must come from a buying marketplace (e.g. Kinguin).
        raise NotImplementedError(
            "G2G OpenAPI has no buy endpoint — sourcing/purchasing from G2G is "
            "not supported. Use Kinguin as the JIT source marketplace."
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
