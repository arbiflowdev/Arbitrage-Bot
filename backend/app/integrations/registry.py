"""Provider registry + adapter factory.

Maps a provider name to its adapter class and builds a ready-to-use adapter,
choosing between the real HTTP-backed implementation and the mock adapter based
on ``settings.MARKETPLACE_MODE``.
"""

from __future__ import annotations

from app.core.config import settings
from app.integrations.base import MarketplaceAdapter, ProviderCredentials
from app.integrations.g2g import G2GAdapter
from app.integrations.http import MarketplaceHTTPClient
from app.integrations.kinguin import KinguinAdapter
from app.integrations.mock import MockAdapter

# Real provider implementations supported in Milestone 2.
_ADAPTERS: dict[str, type[MarketplaceAdapter]] = {
    "kinguin": KinguinAdapter,
    "g2g": G2GAdapter,
}

#: Public tuple of provider identifiers the platform knows about.
SUPPORTED_PROVIDERS: tuple[str, ...] = tuple(_ADAPTERS.keys())


def is_supported(provider: str) -> bool:
    return provider in _ADAPTERS


def resolve_credentials(provider: str) -> ProviderCredentials | None:
    """Return the API credentials for ``provider`` from ``.env``, or None.

    Keys are read directly from settings (``<PROVIDER>_API_KEY`` /
    ``<PROVIDER>_API_SECRET``). This is the single source of credentials —
    paste live keys into ``.env`` and set ``MARKETPLACE_MODE=live`` to go live.
    Returns ``None`` when no key is configured (the adapter then stays dormant
    in live mode, or returns mock data in mock mode).
    """
    env_creds = settings.env_credentials_for(provider)
    if env_creds is None:
        return None
    return ProviderCredentials(
        api_key=env_creds["api_key"],
        api_secret=env_creds["api_secret"],
    )


def _http_for(provider: str) -> MarketplaceHTTPClient:
    config = {
        "kinguin": (
            settings.KINGUIN_API_BASE_URL,
            settings.KINGUIN_RATE_LIMIT_PER_MINUTE,
        ),
        "g2g": (settings.G2G_API_BASE_URL, settings.G2G_RATE_LIMIT_PER_MINUTE),
    }
    base_url, rate = config[provider]
    return MarketplaceHTTPClient(
        provider, base_url, rate_limit_per_minute=rate
    )


def build_adapter(
    provider: str,
    credentials: ProviderCredentials | None = None,
    *,
    mode: str | None = None,
) -> MarketplaceAdapter:
    """Construct an adapter for ``provider``.

    In ``mock`` mode a :class:`MockAdapter` is returned (no keys required). In
    ``live`` mode the real adapter is wired with an HTTP client; it will raise
    ``CredentialsNotConfigured`` on use until an active credential is supplied.
    """
    if provider not in _ADAPTERS:
        raise ValueError(
            f"Unsupported marketplace provider '{provider}'. "
            f"Supported: {', '.join(SUPPORTED_PROVIDERS)}."
        )
    effective_mode = mode or settings.MARKETPLACE_MODE
    if effective_mode == "mock":
        return MockAdapter(provider=provider, credentials=credentials)
    return _ADAPTERS[provider](credentials=credentials, http=_http_for(provider))
