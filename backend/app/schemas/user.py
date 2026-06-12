"""User-facing schemas."""

from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, EmailStr, Field

from app.models.user import UserRole
from app.schemas.common import ORMModel


class UserBase(ORMModel):
    # ``str`` (not ``EmailStr``) on read: input schemas validate email format,
    # but reading existing rows must never 500 on an unusual stored value
    # (e.g. a reserved-domain account created during testing).
    email: str
    full_name: str | None = Field(default=None, max_length=255)


class UserRead(UserBase):
    id: int
    role: UserRole
    is_active: bool
    created_at: datetime
    updated_at: datetime


class UserCreate(BaseModel):
    """Admin-created account. There is no public sign-up; admins provision
    operator accounts here (defaulting to the admin role)."""

    email: EmailStr
    password: str = Field(min_length=8, max_length=128)
    full_name: str | None = Field(default=None, max_length=255)
    role: UserRole = UserRole.ADMIN


class UserUpdate(BaseModel):
    role: UserRole | None = None
    is_active: bool | None = None
