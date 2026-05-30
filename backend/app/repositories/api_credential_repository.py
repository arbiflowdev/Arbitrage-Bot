"""Repository for marketplace API credentials."""

from __future__ import annotations

from sqlalchemy import select

from app.models.api_credential import ApiCredential
from app.repositories.base import BaseRepository


class ApiCredentialRepository(BaseRepository[ApiCredential]):
    model = ApiCredential

    async def get_by_provider(
        self, provider: str, label: str = "default"
    ) -> ApiCredential | None:
        stmt = select(ApiCredential).where(
            ApiCredential.provider == provider,
            ApiCredential.label == label,
        )
        return await self.session.scalar(stmt)
