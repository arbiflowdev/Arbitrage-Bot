"""Application configuration loaded from environment variables.
"""

from __future__ import annotations

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

    # --- JWT / Auth ---
    JWT_SECRET: str = Field(
        default="change-me-in-production-please-use-a-long-random-secret",
        min_length=16,
    )
    JWT_ALGORITHM: str = "HS256"
    ACCESS_TOKEN_EXPIRE_MINUTES: int = 60 * 24  # 24h default

    # --- CORS ---
    # NoDecode prevents pydantic-settings from treating env values as JSON
    # so a plain ``CORS_ORIGINS=*`` (or comma-separated origins) is accepted.
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

    # ------------------------------------------------------------------
    # Database URL helpers
    # ------------------------------------------------------------------
    # ``DATABASE_URL`` accepts either an async SQLAlchemy URL
    # (``postgresql+asyncpg://...``) or a stock Postgres URL
    # (``postgresql://...`` — e.g. the connection string Neon hands you).
    # The helpers below normalise it for the async engine and Alembic.

    @property
    def normalized_database_url(self) -> str:
        """Return the DB URL with async driver + libpq-only params stripped."""
        url = self.DATABASE_URL
        # Only rewrite Postgres URLs — other dialects (e.g. sqlite) need to
        # be passed through untouched because urlunparse mangles paths when
        # netloc is empty (e.g. sqlite:///:memory:).
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
