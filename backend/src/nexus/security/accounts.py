"""User accounts and refresh-token rotation with reuse detection (ADR-0010)."""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import structlog
from sqlalchemy import select, update
from sqlalchemy.ext.asyncio import AsyncSession

from nexus.db.models import RefreshToken, Role, User
from nexus.security.passwords import hash_password, needs_rehash, verify_password
from nexus.security.tokens import hash_refresh_token, new_refresh_token

logger = structlog.get_logger("nexus.security")


class RefreshError(Exception):
    """Refresh token missing, expired, revoked or reused."""


@dataclass(frozen=True, slots=True)
class IssuedRefresh:
    raw: str
    expires_at: datetime


def normalize_email(email: str) -> str:
    return email.strip().lower()


async def authenticate(session: AsyncSession, email: str, password: str) -> User | None:
    user = await session.scalar(select(User).where(User.email == normalize_email(email)))
    ok = verify_password(user.password_hash if user else None, password)
    if not ok or user is None or not user.is_active:
        return None
    if needs_rehash(user.password_hash):
        user.password_hash = hash_password(password)
    return user


async def create_user(
    session: AsyncSession, *, email: str, password: str, display_name: str, role: Role
) -> User:
    user = User(
        email=normalize_email(email),
        display_name=display_name,
        password_hash=hash_password(password),
        role=role,
    )
    session.add(user)
    await session.flush()
    return user


async def ensure_bootstrap_admin(session: AsyncSession, email: str, password: str) -> bool:
    """Create the first admin if no admin exists yet. Returns True if one was created."""
    existing = await session.scalar(select(User.id).where(User.role == Role.ADMIN).limit(1))
    if existing is not None:
        return False
    await create_user(
        session, email=email, password=password, display_name="Administrador", role=Role.ADMIN
    )
    logger.info("security.bootstrap_admin_created", email=normalize_email(email))
    return True


async def issue_refresh(
    session: AsyncSession, user_id: uuid.UUID, ttl_s: int, family_id: uuid.UUID | None = None
) -> IssuedRefresh:
    raw, digest = new_refresh_token()
    expires = datetime.now(UTC) + timedelta(seconds=ttl_s)
    session.add(
        RefreshToken(
            user_id=user_id,
            family_id=family_id or uuid.uuid4(),
            token_hash=digest,
            expires_at=expires,
        )
    )
    await session.flush()
    return IssuedRefresh(raw, expires)


async def _revoke_family(session: AsyncSession, family_id: uuid.UUID) -> None:
    await session.execute(
        update(RefreshToken)
        .where(RefreshToken.family_id == family_id, RefreshToken.revoked_at.is_(None))
        .values(revoked_at=datetime.now(UTC))
    )


async def rotate_refresh(session: AsyncSession, raw: str, ttl_s: int) -> tuple[User, IssuedRefresh]:
    token = await session.scalar(
        select(RefreshToken).where(RefreshToken.token_hash == hash_refresh_token(raw))
    )
    now = datetime.now(UTC)
    if token is None:
        raise RefreshError("unknown token")
    if token.used_at is not None or token.revoked_at is not None:
        # A rotated token presented again means it was stolen: kill the whole session family.
        await _revoke_family(session, token.family_id)
        logger.warning("security.refresh_reuse_detected", user_id=str(token.user_id))
        raise RefreshError("token reuse detected")
    if token.expires_at <= now:
        raise RefreshError("token expired")
    user = await session.get(User, token.user_id)
    if user is None or not user.is_active:
        raise RefreshError("inactive user")
    token.used_at = now
    issued = await issue_refresh(session, user.id, ttl_s, family_id=token.family_id)
    return user, issued


async def revoke_refresh(session: AsyncSession, raw: str) -> None:
    token = await session.scalar(
        select(RefreshToken).where(RefreshToken.token_hash == hash_refresh_token(raw))
    )
    if token is not None:
        await _revoke_family(session, token.family_id)
