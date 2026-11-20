"""Short-lived JWT access tokens and opaque, rotated refresh tokens (ADR-0010)."""

from __future__ import annotations

import hashlib
import secrets
import uuid
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta

import jwt

from nexus.db.models import Role

ISSUER = "nexus-ai"
AUDIENCE = "nexus-api"
ALGORITHM = "HS256"


@dataclass(frozen=True, slots=True)
class AccessClaims:
    user_id: uuid.UUID
    role: Role
    expires_at: datetime


class InvalidTokenError(Exception):
    pass


class TokenService:
    def __init__(self, secret: str, access_ttl_s: int) -> None:
        self._secret = secret
        self.access_ttl_s = access_ttl_s

    def issue_access(self, user_id: uuid.UUID, role: Role, *, now: datetime | None = None) -> str:
        issued = now or datetime.now(UTC)
        payload = {
            "sub": str(user_id),
            "role": role.value,
            "iss": ISSUER,
            "aud": AUDIENCE,
            "iat": issued,
            "nbf": issued,
            "exp": issued + timedelta(seconds=self.access_ttl_s),
            "jti": uuid.uuid4().hex,
        }
        return jwt.encode(payload, self._secret, algorithm=ALGORITHM)

    def decode_access(self, token: str) -> AccessClaims:
        try:
            payload = jwt.decode(
                token,
                self._secret,
                algorithms=[ALGORITHM],  # never trust the header's alg
                audience=AUDIENCE,
                issuer=ISSUER,
                options={"require": ["sub", "role", "exp", "iat", "iss", "aud", "jti"]},
            )
            return AccessClaims(
                user_id=uuid.UUID(payload["sub"]),
                role=Role(payload["role"]),
                expires_at=datetime.fromtimestamp(payload["exp"], UTC),
            )
        except (jwt.PyJWTError, ValueError, KeyError) as exc:
            raise InvalidTokenError(str(exc)) from exc


def new_refresh_token() -> tuple[str, str]:
    """Return (raw token for the cookie, SHA-256 hex digest for storage)."""
    raw = secrets.token_urlsafe(32)
    return raw, hash_refresh_token(raw)


def hash_refresh_token(raw: str) -> str:
    return hashlib.sha256(raw.encode()).hexdigest()
