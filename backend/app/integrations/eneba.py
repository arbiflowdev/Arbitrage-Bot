"""Eneba marketplace adapter.

Targets Eneba's official GraphQL API (production base ``https://api.eneba.com``,
single endpoint ``/graphql/``; sandbox ``https://api-sandbox.eneba.com``). Unlike
Kinguin/G2G — which authenticate with a static API key per request — Eneba is
secured by OAuth 2.0: we exchange a client id + authorization id + secret for a
short-lived Bearer access token at ``https://user.eneba.com/oauth/token`` and
send it on every GraphQL call. The token is cached and transparently refreshed
just before it expires.

Webhooks: Eneba delivers purchase/sale events to a callback URL registered via
the ``P_registerCallback`` mutation, authenticating each delivery with an
``Authorization`` header value WE choose at registration time. So verification
is a constant-time comparison of that shared secret — not a body HMAC like the
other providers.

NOTE: GraphQL operation names (``S_products``, ``S_stock``, ``S_sales``,
``S_createAuction``/``S_updateAuction``) follow Eneba's documented seller API.
Exact selection-set field names and the money minor-unit convention should be
re-verified against the live schema once production credentials are issued; the
adapter stays dormant (raising ``CredentialsNotConfigured``) until then, so it
is safe to ship without keys.
"""

from __future__ import annotations

import hmac
import time
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from app.core.config import settings
from app.core.logging import get_logger
from app.integrations.base import (
    MarketplaceAdapter,
    NormalizedListing,
    NormalizedOrder,
    NormalizedPrice,
    NormalizedProduct,
    ParsedWebhook,
    ProviderCredentials,
    to_decimal,
)
from app.integrations.exceptions import ProviderAPIError

if TYPE_CHECKING:
    from app.integrations.http import MarketplaceHTTPClient

log = get_logger(__name__)

# Refresh the OAuth token this many seconds before it actually expires, so an
# in-flight request never races the expiry boundary.
_TOKEN_REFRESH_SKEW_SECONDS = 60.0


class EnebaAdapter(MarketplaceAdapter):
    provider = "eneba"

    #: Single GraphQL endpoint (relative to the configured base URL).
    _GRAPHQL_PATH = "/graphql/"

    def __init__(
        self,
        credentials: ProviderCredentials | None = None,
        http: MarketplaceHTTPClient | None = None,
    ) -> None:
        super().__init__(credentials, http)
        self._access_token: str | None = None
        self._token_expires_at: float = 0.0

    # ------------------------------------------------------------------
    # OAuth 2.0 token handling
    # ------------------------------------------------------------------
    async def _access_token_value(self) -> str:
        """Return a valid Bearer token, fetching/refreshing it as needed."""
        creds = self._require_credentials()
        now = time.monotonic()
        if self._access_token and now < self._token_expires_at:
            return self._access_token

        extra = creds.extra or {}
        # Eneba's token request is form-encoded with grant_type=api_consumer.
        # ``client_id`` is a FIXED Eneba application id shared by all sellers (not
        # a per-seller credential); the seller's Auth ID goes in ``id`` and the
        # Auth Secret in ``secret``.
        form = {
            "grant_type": "api_consumer",
            "client_id": settings.ENEBA_OAUTH_CLIENT_ID,
            "id": extra.get("auth_id") or creds.api_key or "",
            "secret": creds.api_secret or "",
        }
        token_data = await self.http.request_json(
            "POST",
            settings.ENEBA_OAUTH_TOKEN_URL,
            data=form,
            headers={
                "Content-Type": "application/x-www-form-urlencoded",
                "Accept": "application/json",
            },
        )
        token = (token_data or {}).get("access_token") if isinstance(token_data, dict) else None
        if not token:
            raise ProviderAPIError(
                "Eneba OAuth response did not contain an access_token.",
                payload=token_data,
            )
        expires_in = float((token_data.get("expires_in") if isinstance(token_data, dict) else 0) or 3600)
        self._access_token = token
        # Never schedule the next refresh in the past; keep at least 30s of life.
        self._token_expires_at = now + max(expires_in - _TOKEN_REFRESH_SKEW_SECONDS, 30.0)
        log.info("eneba.token.refreshed", expires_in=expires_in)
        return token

    async def _graphql(
        self, query: str, variables: dict[str, Any] | None = None
    ) -> dict[str, Any]:
        """Execute one GraphQL operation and return its ``data`` object.

        GraphQL returns HTTP 200 even for query errors, so we surface any
        ``errors`` array as a :class:`ProviderAPIError` for the service layer.
        """
        token = await self._access_token_value()
        body = await self.http.request_json(
            "POST",
            self._GRAPHQL_PATH,
            json={"query": query, "variables": variables or {}},
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/json",
            },
        )
        if not isinstance(body, dict):
            return {}
        if body.get("errors"):
            raise ProviderAPIError(
                "Eneba GraphQL returned errors.",
                payload=body["errors"],
            )
        data = body.get("data")
        return data if isinstance(data, dict) else {}

    # ------------------------------------------------------------------
    # Parsing helpers
    # ------------------------------------------------------------------
    @staticmethod
    def _nodes(connection: Any) -> list[dict[str, Any]]:
        """Extract node dicts from a Relay-style ``{edges: [{node}]}`` envelope.

        Falls back to a plain list so either response shape is tolerated.
        """
        if isinstance(connection, dict):
            edges = connection.get("edges") or connection.get("nodes") or []
        elif isinstance(connection, list):
            edges = connection
        else:
            return []
        nodes: list[dict[str, Any]] = []
        for edge in edges:
            if not isinstance(edge, dict):
                continue
            node = edge.get("node", edge)
            if isinstance(node, dict):
                nodes.append(node)
        return nodes

    @staticmethod
    def _money(value: Any) -> Decimal | None:
        """Normalize an Eneba money field to a major-unit ``Decimal``.

        Eneba expresses amounts in minor units (cents), optionally wrapped as
        ``{"amount": 1099, "currency": "EUR"}``. NOTE: confirm the minor-unit
        convention against the live schema for the specific field in use.
        """
        if isinstance(value, dict):
            value = value.get("amount")
        amount = to_decimal(value)
        if amount is None:
            return None
        return amount / Decimal(100)

    @staticmethod
    def _currency(value: Any, default: str = "EUR") -> str:
        if isinstance(value, dict) and value.get("currency"):
            return str(value["currency"])
        return default

    # ------------------------------------------------------------------
    # Read operations
    # ------------------------------------------------------------------
    async def fetch_products(
        self, *, limit: int = 50, page: int = 1
    ) -> list[NormalizedProduct]:
        query = """
        query Products($first: Int) {
          S_products(first: $first) {
            edges {
              node {
                id
                name
                platform
                type
                price { amount currency }
              }
            }
          }
        }
        """
        data = await self._graphql(query, {"first": limit})
        products: list[NormalizedProduct] = []
        for node in self._nodes(data.get("S_products")):
            products.append(
                NormalizedProduct(
                    marketplace_sku=str(node.get("id") or ""),
                    name=str(node.get("name") or ""),
                    price=self._money(node.get("price")),
                    currency=self._currency(node.get("price")),
                    available_qty=node.get("availableStock") or node.get("stock"),
                    region=node.get("region"),
                    platform=node.get("platform"),
                    raw=node,
                )
            )
        return products

    async def fetch_prices(
        self, skus: list[str] | None = None
    ) -> list[NormalizedPrice]:
        # Prices come from the seller's live auctions (S_stock), which carry the
        # current price and available quantity per product.
        query = """
        query Stock($first: Int) {
          S_stock(first: $first) {
            edges {
              node {
                id
                product { id }
                price { amount currency }
                availableStock
              }
            }
          }
        }
        """
        data = await self._graphql(query, {"first": 100})
        wanted = set(skus) if skus else None
        prices: list[NormalizedPrice] = []
        for node in self._nodes(data.get("S_stock")):
            product = node.get("product") if isinstance(node.get("product"), dict) else {}
            sku = str(product.get("id") or node.get("id") or "")
            if wanted is not None and sku not in wanted:
                continue
            price = self._money(node.get("price"))
            if price is None:
                continue
            qty = node.get("availableStock")
            prices.append(
                NormalizedPrice(
                    marketplace_sku=sku,
                    price=price,
                    currency=self._currency(node.get("price")),
                    available_qty=qty,
                    is_available=bool(qty) if qty is not None else True,
                    raw=node,
                )
            )
        return prices

    async def fetch_listings(self) -> list[NormalizedListing]:
        query = """
        query Stock($first: Int) {
          S_stock(first: $first) {
            edges {
              node {
                id
                product { id name }
                price { amount currency }
                availableStock
                status
              }
            }
          }
        }
        """
        data = await self._graphql(query, {"first": 100})
        listings: list[NormalizedListing] = []
        for node in self._nodes(data.get("S_stock")):
            product = node.get("product") if isinstance(node.get("product"), dict) else {}
            listings.append(
                NormalizedListing(
                    marketplace_sku=str(product.get("id") or node.get("id") or ""),
                    external_listing_id=str(node["id"]) if node.get("id") is not None else None,
                    title=product.get("name"),
                    price=self._money(node.get("price")),
                    currency=self._currency(node.get("price")),
                    stock=int(node.get("availableStock") or 0),
                    status=str(node.get("status", "active")),
                    raw=node,
                )
            )
        return listings

    async def fetch_orders(
        self, *, limit: int = 50, page: int = 1
    ) -> list[NormalizedOrder]:
        query = """
        query Sales($first: Int) {
          S_sales(first: $first) {
            edges {
              node {
                id
                orderId
                product { id }
                quantity
                total { amount currency }
                status
              }
            }
          }
        }
        """
        data = await self._graphql(query, {"first": limit})
        orders: list[NormalizedOrder] = []
        for node in self._nodes(data.get("S_sales")):
            product = node.get("product") if isinstance(node.get("product"), dict) else {}
            orders.append(
                NormalizedOrder(
                    external_order_id=str(node.get("orderId") or node.get("id") or ""),
                    marketplace_sku=str(product.get("id") or ""),
                    quantity=int(node.get("quantity", 1) or 1),
                    total=self._money(node.get("total")),
                    currency=self._currency(node.get("total")),
                    status=str(node.get("status", "unknown")),
                    raw=node,
                )
            )
        return orders

    # ------------------------------------------------------------------
    # Write operations
    # ------------------------------------------------------------------
    async def push_listing(self, listing: NormalizedListing) -> NormalizedListing:
        # Eneba auction mutations are asynchronous: they return an action id used
        # to track processing rather than the finished auction, so we report the
        # listing as "pending" until a webhook/poll confirms it.
        price_amount = (
            int((listing.price * Decimal(100)).to_integral_value())
            if listing.price is not None
            else None
        )
        if listing.external_listing_id:
            mutation = """
            mutation UpdateAuction($input: S_API_UpdateAuctionInput!) {
              S_updateAuction(input: $input) { id }
            }
            """
            variables = {
                "input": {
                    "id": listing.external_listing_id,
                    "price": {"amount": price_amount, "currency": listing.currency or "EUR"},
                    "stock": listing.stock,
                }
            }
            result_key = "S_updateAuction"
        else:
            mutation = """
            mutation CreateAuction($input: S_API_CreateAuctionInput!) {
              S_createAuction(input: $input) { id }
            }
            """
            variables = {
                "input": {
                    "productId": listing.marketplace_sku,
                    "price": {"amount": price_amount, "currency": listing.currency or "EUR"},
                    "stock": listing.stock,
                }
            }
            result_key = "S_createAuction"

        data = await self._graphql(mutation, variables)
        result = data.get(result_key) if isinstance(data.get(result_key), dict) else {}
        action_id = result.get("id") if isinstance(result, dict) else None
        return NormalizedListing(
            marketplace_sku=listing.marketplace_sku,
            external_listing_id=str(action_id) if action_id is not None else listing.external_listing_id,
            title=listing.title,
            price=listing.price,
            currency=listing.currency,
            stock=listing.stock,
            status="pending",
            raw={"action_id": action_id},
        )

    # ------------------------------------------------------------------
    # Health & webhooks
    # ------------------------------------------------------------------
    async def health_check(self) -> bool:
        # A minimal authenticated query; success means the OAuth token is valid
        # and the GraphQL endpoint is reachable.
        await self._graphql(
            "query Health { S_products(first: 1) { edges { node { id } } } }"
        )
        return True

    def verify_webhook(self, headers: dict[str, str], body: bytes) -> bool:
        """Verify an Eneba callback.

        Eneba authenticates callbacks with the ``Authorization`` header value we
        supplied when registering via ``P_registerCallback`` (not a body HMAC).
        We compare it in constant time against our configured webhook secret.
        ``body`` is unused but kept for interface parity with other providers.
        """
        expected = (
            (self.credentials.extra or {}).get("webhook_secret")
            if self.credentials
            else None
        ) or ""
        received = headers.get("authorization") or headers.get("Authorization") or ""
        if not expected or not received:
            return False
        return hmac.compare_digest(expected, received)

    def parse_webhook(
        self, headers: dict[str, str], payload: dict[str, Any]
    ) -> ParsedWebhook:
        external_id = payload.get("id") or payload.get("orderId")
        return ParsedWebhook(
            event_type=str(
                payload.get("type")
                or payload.get("event")
                or payload.get("callbackType")
                or "unknown"
            ),
            external_id=str(external_id) if external_id is not None else None,
            data=payload,
        )
