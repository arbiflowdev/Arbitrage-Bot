"""Settings service — exposes safe configuration to authorised callers."""

from __future__ import annotations

from app.core.config import settings
from app.schemas.settings import PublicSettings


class SettingsService:
    @staticmethod
    def get_public_settings() -> PublicSettings:
        return PublicSettings(
            app_name=settings.APP_NAME,
            app_version=settings.APP_VERSION,
            environment=settings.APP_ENV,
            api_prefix=settings.API_V1_PREFIX,
            access_token_expire_minutes=settings.ACCESS_TOKEN_EXPIRE_MINUTES,
            cors_origins=settings.CORS_ORIGINS,
            log_level=settings.LOG_LEVEL,
        )
