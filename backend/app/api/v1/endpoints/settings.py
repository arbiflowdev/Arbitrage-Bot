"""Settings endpoint.

GET /settings returns the runtime configuration that the dashboard and
operators legitimately need to see. Sensitive values (secrets, DSNs,
provider API keys) are intentionally absent and require admin scope.
"""

from __future__ import annotations

from fastapi import APIRouter

from app.core.dependencies import CurrentAdmin
from app.schemas.settings import PublicSettings
from app.services.settings_service import SettingsService

router = APIRouter(tags=["settings"])


@router.get(
    "/settings",
    response_model=PublicSettings,
    summary="Return public runtime settings (admin only)",
)
async def get_settings(_: CurrentAdmin) -> PublicSettings:
    return SettingsService.get_public_settings()
