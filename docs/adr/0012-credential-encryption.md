# ADR-0012 — Encryption of connection credentials

- Status: Accepted
- Date: 2026-11-20

## Decision
- Connection secrets (password, full DSN parameters) are encrypted at rest with **Fernet**
  (`cryptography`: AES-128-CBC + HMAC-SHA256, authenticated) via `MultiFernet`, so keys can rotate:
  `CREDENTIALS_KEYS` is a comma-separated list, first key encrypts, all keys decrypt; `make rotate-keys`
  re-encrypts rows with the newest key.
- Decrypted secrets live only in the engine factory; they are never returned by the API (responses show
  `••••` + a `has_secret` flag), never logged (structlog processor redacts known keys), never sent to the LLM.
- SQLite sources are restricted to files under a configured data directory (no path traversal) and opened
  read-only (ADR-0013).

## Alternatives considered
- pgcrypto in the DB: key would have to travel to the DB in queries.
- Vault/KMS: right for production clusters, overkill for the single-box target; `CredentialCipher` interface keeps
  the seam.
