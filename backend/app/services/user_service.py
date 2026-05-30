"""User service — read/write operations on the User aggregate."""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user import User, UserRole
from app.repositories.user_repository import UserRepository


class UserService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.users = UserRepository(session)

    async def get(self, user_id: int) -> User | None:
        return await self.users.get_by_id(user_id)

    async def set_role(self, user: User, role: UserRole) -> User:
        user.role = role
        await self.session.flush()
        await self.session.commit()
        await self.session.refresh(user)
        return user
