"""Settings endpoint schemas.

Returns only safe, non-secret runtime configuration. Sensitive values
(JWT secret, full database URL, raw API credentials) are explicitly
excluded.
"""

from __future__ import annotations

from pydantic import BaseModel


class PublicSettings(BaseModel):
    app_name: str
    app_version: str
    environment: str
    api_prefix: str
    access_token_expire_minutes: int
    cors_origins: list[str]
    log_level: str
