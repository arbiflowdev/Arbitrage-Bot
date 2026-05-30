"""User-facing schemas."""

from __future__ import annotations

from datetime import datetime

from pydantic import EmailStr, Field

from app.models.user import UserRole
from app.schemas.common import ORMModel


class UserBase(ORMModel):
    email: EmailStr
    full_name: str | None = Field(default=None, max_length=255)


class UserRead(UserBase):
    id: int
    role: UserRole
    is_active: bool
    created_at: datetime
    updated_at: datetime
