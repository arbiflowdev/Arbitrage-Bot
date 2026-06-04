"""Application configuration loaded from environment variables.
"""

from __future__ import annotations

from decimal import Decimal
from functools import lru_cache
from typing import Annotated, Any, Literal
from urllib.parse import parse_qs, parse_qsl, urlencode, urlparse, urlunparse

from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, NoDecode, SettingsConfigDict

# Query parameters that belong to libpq/psycopg but are not understood by
# asyncpg. They must be stripped from the URL and translated to
# connect_args where appropriate.
_LIBPQ_ONLY_QUERY_KEYS = {
    "sslmode",
    "channel_binding",
    "sslcert",
    "sslkey",
    "sslrootcert",
    "sslcompression",
    "sslsni",
    "gssencmode",
    "krbsrvname",
    "target_session_attrs",
}


class Settings(BaseSettings):
    """Strongly-typed application settings."""

    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # --- Application ---
    APP_NAME: str = "Digital Goods Arbitrage Platform"
    APP_ENV: Literal["development", "staging", "production", "test"] = "development"
    APP_VERSION: str = "0.1.0"
    API_V1_PREFIX: str = "/api"
    DEBUG: bool = False

    # --- Server ---
    HOST: str = "0.0.0.0"
    PORT: int = 8000

    # --- Database ---
    # Async SQLAlchemy / asyncpg URL, e.g.
    # postgresql+asyncpg://user:pass@host:5432/dbname
    DATABASE_URL: str = Field(
        default="postgresql+asyncpg://arbitrage:arbitrage@postgres:5432/arbitrage",
    )
    DB_ECHO: bool = False
    DB_POOL_SIZE: int = 10
    DB_MAX_OVERFLOW: int = 20

    # --- Redis ---
    REDIS_URL: str = "redis://redis:6379/0"

    # --- Marketplace integrations ---
    # ``mock`` lets the platform run end-to-end with no real API keys (the
    # default, so the app is usable before credentials exist). ``live`` routes
    # adapters at the real marketplace REST APIs and requires credentials.
    MARKETPLACE_MODE: Literal["mock", "live"] = "mock"

    # Per-provider API base URL. Kinguin/G2G are REST; Eneba is a single
    # GraphQL endpoint (``/graphql/``) under this host.
    KINGUIN_API_BASE_URL: str = "https://gateway.kinguin.net/esa/api"
    G2G_API_BASE_URL: str = "https://open.g2g.com"
    ENEBA_API_BASE_URL: str = "https://api.eneba.com"
    # Eneba is OAuth 2.0: this is where we exchange credentials for a token.
    ENEBA_OAUTH_TOKEN_URL: str = "https://user.eneba.com/oauth/token"

    # Proactive client-side rate limits (requests/minute) enforced via Redis.
    KINGUIN_RATE_LIMIT_PER_MINUTE: int = 60
    G2G_RATE_LIMIT_PER_MINUTE: int = 60
    # Eneba allows 5000 requests / 10 min per IP (~500/min); stay well under.
    ENEBA_RATE_LIMIT_PER_MINUTE: int = 120

    # Shared outbound HTTP behaviour for all marketplace adapters.
    HTTP_TIMEOUT_SECONDS: float = 30.0
    HTTP_MAX_RETRIES: int = 3
    HTTP_RETRY_BACKOFF_SECONDS: float = 0.5

    # --- Marketplace API credentials via .env (optional fallback) ---
    # Drop live keys straight into .env here to go live WITHOUT touching the
    # credentials API/DB. Leave blank to rely on the encrypted-DB credential
    # store instead. When both exist, the DB store wins (it can hold multiple
    # labelled credentials and is encrypted at rest). ``*_API_SECRET`` is the
    # webhook/HMAC signing secret for that provider.
    KINGUIN_API_KEY: str | None = None
    KINGUIN_API_SECRET: str | None = None
    G2G_API_KEY: str | None = None
    G2G_API_SECRET: str | None = None

    # Eneba uses OAuth 2.0 rather than a single API key. Onboarding gives you a
    # client id plus an authorization id + secret, which we exchange for a
    # Bearer token. ``ENEBA_WEBHOOK_SECRET`` is the Authorization header value
    # we register with Eneba (via P_registerCallback) to authenticate inbound
    # callbacks. Leave blank to keep Eneba dormant / in mock mode.
    ENEBA_CLIENT_ID: str | None = None
    ENEBA_AUTH_ID: str | None = None
    ENEBA_API_SECRET: str | None = None
    ENEBA_WEBHOOK_SECRET: str | None = None

    # --- Arbitrage / dynamic pricing engine (Milestone 3) ---
    # Base currency all prices are converted into before any comparison.
    BASE_CURRENCY: str = "EUR"
    # How often the automated pricing scan runs.
    PRICING_SCAN_INTERVAL_SECONDS: int = 60
    # Master on/off for the background scan worker (the Redis kill-switch can
    # also flip this at runtime without a restart). When False, no automated
    # repricing happens.
    PRICING_ENGINE_ENABLED: bool = True
    # When True the engine computes and records decisions but never pushes a
    # price change to the marketplace — a safe "preview" mode for first runs.
    PRICING_DRY_RUN: bool = False

    # Strategy thresholds (the client's "financial red line" and tactics).
    PRICING_UNDERCUT_AMOUNT: Decimal = Decimal("0.01")
    PRICING_MIN_PROFIT_ABSOLUTE: Decimal = Decimal("0.30")
    PRICING_MIN_PROFIT_MARGIN_PERCENT: Decimal = Decimal("5")
    PRICING_ANOMALY_DROP: Decimal = Decimal("0.50")
    PRICING_FALLBACK_RANK: int = 3

    # FX: free exchange-rate feed + safety buffer against intra-day swings.
    EXCHANGE_RATE_API_URL: str = "https://open.er-api.com/v6/latest"
    EXCHANGE_RATE_TTL_SECONDS: int = 3600
    CURRENCY_BUFFER_PERCENT: Decimal = Decimal("1")

    # Composite marketplace fees: (percentage fee + fixed fee) per platform,
    # plus withdrawal/payout buffers. These are the adjustable defaults; a
    # ``fee_structures`` DB row for a provider/category overrides them.
    KINGUIN_FEE_PERCENT: Decimal = Decimal("11")
    KINGUIN_FEE_FIXED: Decimal = Decimal("0.35")
    G2G_FEE_PERCENT: Decimal = Decimal("9.9")
    G2G_FEE_FIXED: Decimal = Decimal("0")
    ENEBA_FEE_PERCENT: Decimal = Decimal("12")
    ENEBA_FEE_FIXED: Decimal = Decimal("0.30")
    # Withdrawal/payout buffers (global defaults; per-provider rows can override
    # via the fee_structures table).
    MARKETPLACE_WITHDRAWAL_PERCENT: Decimal = Decimal("0")
    MARKETPLACE_WITHDRAWAL_FIXED: Decimal = Decimal("0")

    # --- JWT / Auth ---
    JWT_SECRET: str = Field(
        default="change-me-in-production-please-use-a-long-random-secret",
        min_length=16,
    )
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24  # 24h default

    # --- CORS ---
    # NoDecode prevents pydantic-settings from treating env values as JSON
    CORS_ORIGINS: Annotated[list[str], NoDecode] = Field(default_factory=lambda: ["*"])

    # --- Logging ---
    LOG_LEVEL: Literal["DEBUG", "INFO", "WARNING", "ERROR", "CRITICAL"] = "INFO"
    LOG_JSON: bool = True

    # --- Bootstrap admin (optional) ---
    # If both set, a default admin will be ensured on startup. Useful for
    # provisioning the very first admin without a manual SQL step.
    BOOTSTRAP_ADMIN_EMAIL: str | None = None
    BOOTSTRAP_ADMIN_PASSWORD: str | None = None

    @field_validator("CORS_ORIGINS", mode="before")
    @classmethod
    def _split_cors(cls, value: object) -> object:
        """Accept comma-separated string or list for CORS_ORIGINS."""
        if isinstance(value, str):
            return [origin.strip() for origin in value.split(",") if origin.strip()]
        return value

    @property
    def is_production(self) -> bool:
        return self.APP_ENV == "production"

    def env_credentials_for(self, provider: str) -> dict[str, Any] | None:
        """Return API keys supplied directly via .env for ``provider``, if any.

        Lets an operator go live by pasting keys into ``.env`` instead of using
        the credentials API. Returns ``None`` when no API key is set for the
        provider (so the encrypted-DB store / mock mode remains in control).

        Eneba is special: it authenticates with OAuth 2.0, so it carries a
        client id (``api_key``), a secret, and additional values (the
        authorization id + webhook secret) under ``extra``.
        """
        if provider == "eneba":
            if not self.ENEBA_CLIENT_ID:
                return None
            return {
                "api_key": self.ENEBA_CLIENT_ID,
                "api_secret": self.ENEBA_API_SECRET,
                "extra": {
                    "auth_id": self.ENEBA_AUTH_ID,
                    "webhook_secret": self.ENEBA_WEBHOOK_SECRET,
                },
            }

        mapping: dict[str, tuple[str | None, str | None]] = {
            "kinguin": (self.KINGUIN_API_KEY, self.KINGUIN_API_SECRET),
            "g2g": (self.G2G_API_KEY, self.G2G_API_SECRET),
        }
        pair = mapping.get(provider)
        if not pair or not pair[0]:
            return None
        return {"api_key": pair[0], "api_secret": pair[1]}

    # ------------------------------------------------------------------
    # Pricing-engine helpers
    # ------------------------------------------------------------------
    def fee_defaults_for(self, provider: str) -> dict[str, Decimal]:
        """Composite fee defaults for a provider (percentages as fractions)."""
        percent_fixed: dict[str, tuple[Decimal, Decimal]] = {
            "kinguin": (self.KINGUIN_FEE_PERCENT, self.KINGUIN_FEE_FIXED),
            "g2g": (self.G2G_FEE_PERCENT, self.G2G_FEE_FIXED),
            "eneba": (self.ENEBA_FEE_PERCENT, self.ENEBA_FEE_FIXED),
        }
        percent, fixed = percent_fixed.get(provider, (Decimal("0"), Decimal("0")))
        return {
            "sales_percent": percent / Decimal("100"),
            "sales_fixed": fixed,
            "withdrawal_percent": self.MARKETPLACE_WITHDRAWAL_PERCENT / Decimal("100"),
            "withdrawal_fixed": self.MARKETPLACE_WITHDRAWAL_FIXED,
        }

    def provider_currency(self, provider: str) -> str:
        """The currency a provider primarily trades in.

        G2G operates mainly in USD; Kinguin and Eneba in EUR. Used to convert
        observed prices into the base currency before any comparison.
        """
        return {"g2g": "USD"}.get(provider, self.BASE_CURRENCY)

    # ------------------------------------------------------------------
    # Database URL helpers
    # ------------------------------------------------------------------

    @property
    def normalized_database_url(self) -> str:
        """Return the DB URL with async driver + libpq-only params stripped."""
        url = self.DATABASE_URL
        if not url.startswith(("postgres://", "postgresql://", "postgresql+")):
            return url

        parsed = urlparse(url)
        scheme = parsed.scheme
        if scheme in {"postgres", "postgresql"}:
            scheme = "postgresql+asyncpg"

        new_query = urlencode(
            [
                (key, value)
                for key, value in parse_qsl(parsed.query, keep_blank_values=True)
                if key.lower() not in _LIBPQ_ONLY_QUERY_KEYS
            ]
        )
        return urlunparse(parsed._replace(scheme=scheme, query=new_query))

    @property
    def db_connect_args(self) -> dict[str, Any]:
        """Extra kwargs forwarded to asyncpg.connect via SQLAlchemy."""
        parsed = urlparse(self.DATABASE_URL)
        if not parsed.scheme.startswith("postgres"):
            return {}

        query = parse_qs(parsed.query)
        sslmode = (query.get("sslmode") or [None])[0]
        hostname = (parsed.hostname or "").lower()

        args: dict[str, Any] = {}

        # SSL: honour libpq-style sslmode, and default to TLS for known
        # managed providers that require it (Neon).
        if sslmode and sslmode != "disable":
            args["ssl"] = True
        elif hostname.endswith(".neon.tech"):
            args["ssl"] = True

        # PgBouncer / connection-poolers in transaction mode break asyncpg
        # prepared statements. Disable the cache when the host looks
        # like a pooler endpoint (Neon's "-pooler" or generic pgbouncer).
        if "pooler" in hostname or "pgbouncer" in hostname:
            args["statement_cache_size"] = 0

        return args


@lru_cache
def get_settings() -> Settings:
    """Return a cached singleton of application settings."""
    return Settings()


settings = get_settings()
