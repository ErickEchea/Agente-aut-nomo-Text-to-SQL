"""Authentication endpoints: login, refresh (rotating cookie), logout, me."""

from __future__ import annotations

import uuid

from fastapi import APIRouter, HTTPException, Request, Response, status
from pydantic import BaseModel, Field

from nexus.api.deps import AuthenticatedUser, Services, Session, client_ip, enforce_rate_limit
from nexus.db.models import AuditLog, Role, User
from nexus.security.accounts import (
    RefreshError,
    authenticate,
    issue_refresh,
    normalize_email,
    revoke_refresh,
    rotate_refresh,
)

router = APIRouter(prefix="/api/auth", tags=["auth"])

REFRESH_COOKIE = "nexus_refresh"
COOKIE_PATH = "/api/auth"


class LoginRequest(BaseModel):
    email: str = Field(min_length=3, max_length=320)
    password: str = Field(min_length=1, max_length=256)


class UserOut(BaseModel):
    id: uuid.UUID
    email: str
    display_name: str
    role: Role


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"  # noqa: S105 — OAuth2 token type, not a secret
    expires_in: int
    user: UserOut


def _set_refresh_cookie(response: Response, services: Services, raw: str) -> None:
    response.set_cookie(
        REFRESH_COOKIE,
        raw,
        max_age=services.settings.security.refresh_token_ttl_s,
        httponly=True,
        secure=services.settings.security.cookie_secure,
        samesite="strict",
        path=COOKIE_PATH,
    )


def _token_response(services: Services, user: User) -> TokenResponse:
    return TokenResponse(
        access_token=services.tokens.issue_access(user.id, user.role),
        expires_in=services.tokens.access_ttl_s,
        user=UserOut(id=user.id, email=user.email, display_name=user.display_name, role=user.role),
    )


@router.post("/login")
async def login(
    body: LoginRequest, request: Request, response: Response, services: Services, session: Session
) -> TokenResponse:
    ip = client_ip(request)
    enforce_rate_limit(services, "login", ip)
    enforce_rate_limit(services, "login", normalize_email(body.email))
    user = await authenticate(session, body.email, body.password)
    session.add(
        AuditLog(
            user_id=user.id if user else None,
            action="login",
            question=normalize_email(body.email),
            outcome="ok" if user else "denied",
            client_ip=ip,
        )
    )
    if user is None:
        await session.commit()
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid email or password")
    issued = await issue_refresh(session, user.id, services.settings.security.refresh_token_ttl_s)
    await session.commit()
    _set_refresh_cookie(response, services, issued.raw)
    return _token_response(services, user)


@router.post("/refresh")
async def refresh(
    request: Request, response: Response, services: Services, session: Session
) -> TokenResponse:
    enforce_rate_limit(services, "default", client_ip(request))
    raw = request.cookies.get(REFRESH_COOKIE)
    if not raw:
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "no refresh token")
    try:
        user, issued = await rotate_refresh(
            session, raw, services.settings.security.refresh_token_ttl_s
        )
    except RefreshError:
        await session.commit()  # persist a family revocation on reuse
        response.delete_cookie(REFRESH_COOKIE, path=COOKIE_PATH)
        raise HTTPException(status.HTTP_401_UNAUTHORIZED, "invalid refresh token") from None
    await session.commit()
    _set_refresh_cookie(response, services, issued.raw)
    return _token_response(services, user)


@router.post("/logout", status_code=status.HTTP_204_NO_CONTENT)
async def logout(request: Request, response: Response, session: Session) -> Response:
    raw = request.cookies.get(REFRESH_COOKIE)
    if raw:
        await revoke_refresh(session, raw)
        await session.commit()
    response.status_code = status.HTTP_204_NO_CONTENT
    response.delete_cookie(REFRESH_COOKIE, path=COOKIE_PATH)
    return response


@router.get("/me")
async def me(user: AuthenticatedUser) -> UserOut:
    return UserOut(id=user.id, email=user.email, display_name=user.display_name, role=user.role)
