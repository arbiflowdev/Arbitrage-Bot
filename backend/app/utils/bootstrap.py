"""One-time bootstrap helpers run on application startup."""

from __future__ import annotations

from app.core.database import AsyncSessionLocal
from app.core.logging import get_logger
from app.core.security import hash_password
from app.models.user import User, UserRole
from app.repositories.user_repository import UserRepository

log = get_logger(__name__)


async def ensure_bootstrap_admin(email: str | None, password: str | None) -> None:
    """Ensure a default admin exists when BOOTSTRAP_ADMIN_* env vars are set.

    Idempotent: a no-op when the user already exists, and short-circuits
    when either env var is missing.
    """
    if not email or not password:
        return

    async with AsyncSessionLocal() as session:
        repo = UserRepository(session)
        existing = await repo.get_by_email(email.lower())
        if existing is not None:
            return

        admin = User(
            email=email.lower(),
            hashed_password=hash_password(password),
            full_name="Bootstrap Admin",
            role=UserRole.ADMIN,
            is_active=True,
        )
        await repo.add(admin)
        await session.commit()
        log.info("bootstrap.admin_created", email=admin.email)
