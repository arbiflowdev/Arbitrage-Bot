"""G2G marketplace adapter.

Targets the G2G OpenAPI, base ``https://open-api.g2g.com``. Every request is
signed: headers ``g2g-api-key``, ``g2g-userid``, ``g2g-timestamp`` (ms) and
``g2g-signature`` = HMAC-SHA256(path + api_key + user_id + timestamp, secret).

G2G is wired as a SELL/deliver destination: :meth:`deliver` posts codes to
``/v2/orders/{id}/delivery``. The OpenAPI is seller-side and exposes no buy
endpoint, so :meth:`purchase` is unsupported (source via Kinguin instead). The
OpenAPI officially supports Gift Card & Top Up products.

Read/sync is wired to the signed v2 endpoints (docs.g2g.com): ``fetch_listings``
and ``fetch_prices`` page through ``POST /v2/offers/search`` (the seller's own
offers — ``payload.results[]`` carrying ``offer_id``/``unit_price``/
``available_qty``/``status``); repricing pushes via ``PATCH /v2/offers/{id}``
(``unit_price`` + ``api_qty``). The marketplace SKU for a G2G mapping is the
``offer_id``. ``GET /v2/products`` is catalogue metadata only (no prices), so it
is not a pricing source. The adapter stays dormant until a credential is set.
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

    #: Bounded pagination for offer search (page_size 100, up to 1000 offers).
    _SEARCH_PAGE_SIZE = 100
    _SEARCH_MAX_PAGES = 10

    async def _search_offers(
        self, *, status: str = "live", query: str | None = None
    ) -> list[dict[str, Any]]:
        """Page through the seller's offers via ``POST /v2/offers/search``.

        The G2G Seller OpenAPI exposes no bulk ``GET /v2/offers``; the search
        endpoint returns the authenticated seller's own offers (the response
        carries our ``seller_id``), filtered by status (default ``live``). We
        page until a short page or the safety cap, signing every request.
        """
        path = "/v2/offers/search"
        results: list[dict[str, Any]] = []
        for page in range(1, self._SEARCH_MAX_PAGES + 1):
            filter_: dict[str, Any] = {"status": status}
            if query:
                filter_["query"] = query
            body = {
                "filter": filter_,
                "page_size": self._SEARCH_PAGE_SIZE,
                "page": page,
            }
            data = await self.http.request_json(
                "POST",
                path,
                json=body,
                headers=self._signed_headers(path, json_body=True),
            )
            items = self._items(data)
            results.extend(items)
            if len(items) < self._SEARCH_PAGE_SIZE:
                break
        return results

    async def fetch_products(
        self, *, limit: int = 50, page: int = 1
    ) -> list[NormalizedProduct]:
        """Catalogue metadata via ``GET /v2/products`` (no pricing).

        Requires a ``brand_id`` (and ``service_id``) — supplied via credential
        ``extra``; without them G2G returns 400, so we stay quiet and return [].
        """
        extra = (self.credentials.extra if self.credentials else None) or {}
        brand_id = extra.get("brand_id")
        service_id = extra.get("service_id")
        if not brand_id or not service_id:
            return []
        params: dict[str, Any] = {"brand_id": brand_id, "service_id": service_id}
        if extra.get("category_id"):
            params["category_id"] = extra["category_id"]
        data = await self.http.request_json(
            "GET",
            "/v2/products",
            params=params,
            headers=self._signed_headers("/v2/products"),
        )
        payload = data.get("payload", {}) if isinstance(data, dict) else {}
        product_list = payload.get("product_list", []) if isinstance(payload, dict) else []
        return [
            NormalizedProduct(
                marketplace_sku=str(item.get("product_id") or ""),
                name=str(item.get("product_name") or ""),
                region=item.get("region_name"),
                platform=item.get("brand_name"),
                raw=item,
            )
            for item in product_list
            if isinstance(item, dict)
        ]

    async def fetch_prices(
        self, skus: list[str] | None = None
    ) -> list[NormalizedPrice]:
        wanted = set(skus) if skus else None
        prices: list[NormalizedPrice] = []
        for item in await self._search_offers():
            sku = self._sku_of(item)
            if wanted is not None and sku not in wanted:
                continue
            price = to_decimal(item.get("unit_price") or item.get("price"))
            if price is None:
                continue
            qty = item.get("available_qty")
            if qty is None:
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
        listings: list[NormalizedListing] = []
        for item in await self._search_offers():
            offer_id = item.get("offer_id")
            qty = item.get("available_qty")
            if qty is None:
                qty = item.get("available_stock") or 0
            listings.append(
                NormalizedListing(
                    marketplace_sku=self._sku_of(item),
                    external_listing_id=str(offer_id)
                    if offer_id is not None
                    else None,
                    title=item.get("title") or item.get("offer_title"),
                    price=to_decimal(item.get("unit_price") or item.get("price")),
                    currency=str(item.get("currency", "USD")),
                    stock=int(qty or 0),
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
        """Reprice/restock an existing offer via ``PATCH /v2/offers/{offer_id}``.

        The repricer only ever updates an offer it already synced, so an
        ``offer_id`` (carried as ``external_listing_id``, falling back to the
        mapped ``marketplace_sku``) is required. Creating a brand-new offer
        needs catalogue attributes the repricer does not have, so that is not
        attempted here.
        """
        offer_id = listing.external_listing_id or listing.marketplace_sku
        if not offer_id:
            raise ProviderAPIError(
                "G2G push_listing requires an offer_id (external_listing_id or "
                "marketplace_sku); creating new offers via the repricer is not "
                "supported."
            )
        payload: dict[str, Any] = {}
        if listing.price is not None:
            payload["unit_price"] = str(listing.price)
        payload["api_qty"] = listing.stock
        path = f"/v2/offers/{offer_id}"
        data = await self.http.request_json(
            "PATCH",
            path,
            json=payload,
            headers=self._signed_headers(path, json_body=True),
        )
        item = data.get("payload", {}) if isinstance(data, dict) else {}
        if not isinstance(item, dict):
            item = {}
        return NormalizedListing(
            marketplace_sku=listing.marketplace_sku,
            external_listing_id=str(item.get("offer_id"))
            if item.get("offer_id") is not None
            else offer_id,
            title=listing.title,
            price=listing.price,
            currency=listing.currency,
            stock=listing.stock,
            status=str(item.get("status", "synced")),
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
        path = "/v2/offers/search"
        await self.http.request_json(
            "POST",
            path,
            json={"filter": {"status": "live"}, "page_size": 1, "page": 1},
            headers=self._signed_headers(path, json_body=True),
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
