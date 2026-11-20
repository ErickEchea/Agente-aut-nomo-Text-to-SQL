import uuid
from datetime import UTC, datetime, timedelta

import jwt
import pytest

from nexus.db.models import Role
from nexus.security.passwords import hash_password, verify_password
from nexus.security.rate_limit import TokenBucketLimiter
from nexus.security.tokens import (
    ALGORITHM,
    AUDIENCE,
    ISSUER,
    InvalidTokenError,
    TokenService,
    hash_refresh_token,
    new_refresh_token,
)

SECRET = "k" * 48
SERVICE = TokenService(SECRET, access_ttl_s=900)
USER = uuid.uuid4()


def test_access_token_round_trip() -> None:
    claims = SERVICE.decode_access(SERVICE.issue_access(USER, Role.ANALYST))
    assert claims.user_id == USER
    assert claims.role is Role.ANALYST
    assert claims.expires_at > datetime.now(UTC)


def test_expired_token_is_rejected() -> None:
    token = SERVICE.issue_access(USER, Role.ADMIN, now=datetime.now(UTC) - timedelta(hours=1))
    with pytest.raises(InvalidTokenError):
        SERVICE.decode_access(token)


def test_token_signed_with_another_secret_is_rejected() -> None:
    token = TokenService("z" * 48, 900).issue_access(USER, Role.ADMIN)
    with pytest.raises(InvalidTokenError):
        SERVICE.decode_access(token)


def test_alg_none_and_tampered_role_are_rejected() -> None:
    payload = {"sub": str(USER), "role": "admin", "iss": ISSUER, "aud": AUDIENCE,
               "iat": datetime.now(UTC), "exp": datetime.now(UTC) + timedelta(minutes=5), "jti": "x"}  # fmt: skip
    unsigned = jwt.encode(payload, key=None, algorithm="none")
    with pytest.raises(InvalidTokenError):
        SERVICE.decode_access(unsigned)
    header, body, signature = SERVICE.issue_access(USER, Role.VIEWER).split(".")
    forged_body = jwt.utils.base64url_encode(
        jwt.api_jws.json.dumps(
            {
                **jwt.decode(
                    f"{header}.{body}.{signature}",
                    SECRET,
                    algorithms=[ALGORITHM],
                    audience=AUDIENCE,
                ),
                "role": "admin",
            }
        ).encode()
    ).decode()
    with pytest.raises(InvalidTokenError):
        SERVICE.decode_access(f"{header}.{forged_body}.{signature}")


def test_wrong_audience_or_missing_claims_are_rejected() -> None:
    token = jwt.encode(
        {"sub": str(USER), "role": "admin", "aud": "other"}, SECRET, algorithm=ALGORITHM
    )
    with pytest.raises(InvalidTokenError):
        SERVICE.decode_access(token)


def test_refresh_tokens_are_random_and_stored_hashed() -> None:
    raw1, hash1 = new_refresh_token()
    raw2, _ = new_refresh_token()
    assert raw1 != raw2
    assert len(raw1) >= 40
    assert hash1 == hash_refresh_token(raw1)
    assert raw1 not in hash1


def test_password_hashing() -> None:
    hashed = hash_password("correct horse battery")
    assert hashed.startswith("$argon2id$")
    assert verify_password(hashed, "correct horse battery")
    assert not verify_password(hashed, "wrong password!!")
    assert not verify_password(None, "anything at all")
    with pytest.raises(ValueError, match="12 characters"):
        hash_password("short")


def test_token_bucket_allows_burst_then_limits_and_refills() -> None:
    now = [0.0]
    limiter = TokenBucketLimiter(clock=lambda: now[0])
    decisions = [limiter.hit("ip", 5) for _ in range(6)]
    assert [d.allowed for d in decisions] == [True] * 5 + [False]
    assert decisions[-1].retry_after_s == 12  # 60 s / 5 per minute
    now[0] += 12
    assert limiter.hit("ip", 5).allowed
    assert limiter.hit("other", 5).allowed  # keys are independent


def test_token_bucket_memory_is_bounded() -> None:
    now = [0.0]
    limiter = TokenBucketLimiter(clock=lambda: now[0], max_keys=100)
    for i in range(1000):
        limiter.hit(f"k{i}", 10)
    assert len(limiter._buckets) <= 100
