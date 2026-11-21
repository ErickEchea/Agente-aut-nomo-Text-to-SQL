"""FastAPI dependencies: services, DB sessions, authentication, RBAC and rate limiting."""

from __future__ import annotations

import uuid
from collections.abc import AsyncIterator, Awaitable, Callable
from dataclasses import dataclass
from typing import Annotated, Literal

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.config import Settings
from nexus.datasources.registry import ConnectionRegistry
from nexus.db.models import Role, User
from nexus.memory.store import ExampleIndexer
from nexus.runs.manager import RunManager
from nexus.security.rate_limit import TokenBucketLimiter
from nexus.security.tokens import InvalidTokenError, TokenService


@dataclass(frozen=True, slots=True)
class AppServices:
    settings: Settings
    sessions: async_sessionmaker[AsyncSession]
    tokens: TokenService
    limiter: TokenBucketLimiter
    runs: RunManager
    examples: ExampleIndexer
    registry: ConnectionRegistry


@dataclass(frozen=True, slots=True)
class CurrentUser:
    id: uuid.UUID
    email: str
    display_name: str
    role: Role


def get_services(request: Request) -> AppServices:
    services: AppServices | None = getattr(request.app.state, "services", None)
    if services is None:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, "service is starting")
    return services


Services = Annotated[AppServices, Depends(get_services)]


async def get_session(services: Services) -> AsyncIterator[AsyncSession]:
    async with services.sessions() as session:
        yield session


Session = Annotated[AsyncSession, Depends(get_session)]


def client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


_UNAUTHORIZED = HTTPException(
    status.HTTP_401_UNAUTHORIZED, "not authenticated", headers={"WWW-Authenticate": "Bearer"}
)


async def get_current_user(request: Request, services: Services, session: Session) -> CurrentUser:
    header = request.headers.get("authorization", "")
    scheme, _, token = header.partition(" ")
    if scheme.lower() != "bearer" or not token:
        raise _UNAUTHORIZED
    try:
        claims = services.tokens.decode_access(token)
    except InvalidTokenError:
        raise _UNAUTHORIZED from None
    user = await session.get(User, claims.user_id)
    if user is None or not user.is_active:
        raise _UNAUTHORIZED
    # The role in the database wins over the token (a demoted user loses rights immediately).
    return CurrentUser(user.id, user.email, user.display_name, user.role)


AuthenticatedUser = Annotated[CurrentUser, Depends(get_current_user)]


def require_roles(*roles: Role) -> Callable[[CurrentUser], Awaitable[CurrentUser]]:
    async def check(user: AuthenticatedUser) -> CurrentUser:
        if user.role not in roles:
            raise HTTPException(status.HTTP_403_FORBIDDEN, "insufficient role")
        return user

    return check


Bucket = Literal["login", "runs", "default"]


def enforce_rate_limit(services: AppServices, bucket: Bucket, key: str) -> None:
    limits = services.settings.rate_limit
    per_minute = {
        "login": limits.login_per_minute,
        "runs": limits.runs_per_minute,
        "default": limits.default_per_minute,
    }[bucket]
    decision = services.limiter.hit(f"{bucket}:{key}", per_minute)
    if not decision.allowed:
        raise HTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "too many requests",
            headers={
                "Retry-After": str(decision.retry_after_s),
                "RateLimit-Limit": str(decision.limit),
                "RateLimit-Remaining": "0",
                "RateLimit-Reset": str(decision.reset_s),
            },
        )
