"""Connection secrets at rest (ADR-0012): Fernet (AES-128-CBC + HMAC-SHA256) with key rotation.

``NEXUS_CREDENTIALS_KEYS`` is a comma-separated list. The first key encrypts; every key decrypts, so
a new key can be prepended and old rows re-encrypted (``nexus-admin rotate-keys``) before the old
key is removed. A key may be a Fernet key or any secret of 32+ characters (derived with SHA-256).
"""

from __future__ import annotations

import base64
import binascii
import hashlib

from cryptography.fernet import Fernet, InvalidToken, MultiFernet

MIN_SECRET_LENGTH = 32


class CredentialError(Exception):
    """Missing keys, or a secret no configured key can decrypt."""


def _fernet(secret: str) -> Fernet:
    raw = secret.strip()
    try:
        if len(base64.urlsafe_b64decode(raw.encode())) == 32:
            return Fernet(raw.encode())
    except (binascii.Error, ValueError):
        pass
    if len(raw) < MIN_SECRET_LENGTH:
        raise CredentialError(f"credential keys must be at least {MIN_SECRET_LENGTH} characters")
    return Fernet(base64.urlsafe_b64encode(hashlib.sha256(raw.encode()).digest()))


class CredentialCipher:
    def __init__(self, keys: str) -> None:
        parts = [k for k in (p.strip() for p in keys.split(",")) if k]
        if not parts:
            raise CredentialError("NEXUS_CREDENTIALS_KEYS is empty")
        self._cipher = MultiFernet([_fernet(k) for k in parts])

    def encrypt(self, secret: str) -> str:
        return self._cipher.encrypt(secret.encode()).decode("ascii")

    def decrypt(self, token: str) -> str:
        try:
            return self._cipher.decrypt(token.encode("ascii")).decode()
        except InvalidToken as exc:
            raise CredentialError("no configured key can decrypt this secret") from exc

    def rotate(self, token: str) -> str:
        """Re-encrypt with the newest (first) key."""
        try:
            return self._cipher.rotate(token.encode("ascii")).decode("ascii")
        except InvalidToken as exc:
            raise CredentialError("no configured key can decrypt this secret") from exc
