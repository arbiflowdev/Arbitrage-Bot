"""Authentication service: registration, login, token issuance."""

from __future__ import annotations

from fastapi import HTTPException, status
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.config import settings
from app.core.logging import get_logger
from app.core.security import create_access_token, hash_password, verify_password
from app.models.user import User, UserRole
from app.repositories.user_repository import UserRepository
from app.schemas.auth import LoginRequest, RegisterRequest, TokenResponse

log = get_logger(__name__)


class AuthService:
    def __init__(self, session: AsyncSession) -> None:
        self.session = session
        self.users = UserRepository(session)

    # ---- registration -----------------------------------------------------

    async def register(self, payload: RegisterRequest) -> User:
        email = payload.email.lower()
        if await self.users.email_exists(email):
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail="A user with this email already exists.",
            )

        user = User(
            email=email,
            hashed_password=hash_password(payload.password),
            full_name=payload.full_name,
            role=UserRole.USER,
            is_active=True,
        )
        await self.users.add(user)
        await self.session.commit()
        await self.session.refresh(user)
        log.info("user.registered", user_id=user.id, email=user.email)
        return user

    # ---- login ------------------------------------------------------------

    async def authenticate(self, payload: LoginRequest) -> User:
        user = await self.users.get_by_email(payload.email.lower())
        # Always run verify_password — even when the user does not exist —
        # so timing does not leak which emails are registered.
        password_ok = verify_password(
            payload.password,
            user.hashed_password if user else _DUMMY_HASH,
        )
        if not user or not password_ok:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="Invalid email or password.",
            )
        if not user.is_active:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail="User account is inactive.",
            )
        log.info("user.login", user_id=user.id, email=user.email)
        return user

    # ---- token helpers ----------------------------------------------------

    def issue_token(self, user: User) -> TokenResponse:
        token = create_access_token(subject=str(user.id), role=user.role.value)
        return TokenResponse(
            access_token=token,
            expires_in=settings.ACCESS_TOKEN_EXPIRE_MINUTES * 60,
        )


# Pre-computed bcrypt hash of an unguessable value, used to keep the
# authenticate() path constant-time when an email is not found. The
# actual plaintext does not matter — verify_password will always fail.
_DUMMY_HASH = (
    "$2b$12$CjwlPmlPUKWQ0kZmGdSj6OoyPRiL0e0DV6QjB6Q1lMcW2gXkz7E5K"
)
