"""Generic base repository providing common async CRUD methods."""

from __future__ import annotations

from typing import Any, Generic, TypeVar

from sqlalchemy import delete, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.base import Base

ModelT = TypeVar("ModelT", bound=Base)


class BaseRepository(Generic[ModelT]):
    """CRUD helpers; subclasses set ``model`` and add domain queries."""

    model: type[ModelT]

    def __init__(self, session: AsyncSession) -> None:
        self.session = session

    async def get_by_id(self, item_id: int) -> ModelT | None:
        return await self.session.get(self.model, item_id)

    async def list(self, *, limit: int = 50, offset: int = 0) -> list[ModelT]:
        stmt = select(self.model).limit(limit).offset(offset).order_by(self.model.id)
        result = await self.session.scalars(stmt)
        return list(result.all())

    async def count(self) -> int:
        result = await self.session.scalar(select(func.count()).select_from(self.model))
        return int(result or 0)

    async def add(self, instance: ModelT, *, flush: bool = True) -> ModelT:
        self.session.add(instance)
        if flush:
            await self.session.flush()
        return instance

    async def update(self, instance: ModelT, data: dict[str, Any]) -> ModelT:
        for key, value in data.items():
            setattr(instance, key, value)
        await self.session.flush()
        return instance

    async def delete(self, item_id: int) -> int:
        result = await self.session.execute(
            delete(self.model).where(self.model.id == item_id)
        )
        return int(result.rowcount or 0)
