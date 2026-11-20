# ADR-0010 — Authentication and authorization

- Status: Accepted
- Date: 2026-11-20

## Decision
- Passwords: Argon2id (`argon2-cffi`, library defaults ≥ OWASP minimums).
- **Access token**: JWT (HS256, `pyjwt`), 15 min, claims `sub`, `role`, `jti`, `iat`, `exp`, `iss`, `aud`;
  sent as `Authorization: Bearer`; kept in memory on the client (never localStorage).
- **Refresh token**: opaque random 256-bit, stored hashed in `refresh_tokens`, rotated on every use with reuse
  detection (reuse revokes the family); delivered as `HttpOnly; Secure; SameSite=Strict` cookie scoped to
  `/api/auth`.
- **Roles** (RBAC via FastAPI dependencies):
  | Capability | viewer | analyst | admin |
  |---|---|---|---|
  | Ask questions, view results/dashboards shared with them | ✓ | ✓ | ✓ |
  | Pin to dashboards, give feedback, mark verified | | ✓ | ✓ |
  | Manage connections, glossary, PII config | | | ✓ |
  | Audit log, user management, run benchmark | | | ✓ |
- First admin is created from `.env` (`NEXUS_BOOTSTRAP_ADMIN_EMAIL/PASSWORD`) on first start only; demo users
  for the other roles are created by `make seed-users` (dev only).
- CORS: explicit origin list from env; no wildcard with credentials. Security headers (CSP, HSTS behind TLS,
  `X-Content-Type-Options`, `Referrer-Policy`, `frame-ancestors 'none'`) set by nginx and the API.
- Secrets only from environment (`.env`, never committed; `.env.example` documents every variable). Startup fails
  fast if `JWT_SECRET` or `CREDENTIALS_KEY` are missing or weak.

## Alternatives considered
- Session cookies only: simpler but couples the API to cookie auth for SSE/fetch and complicates CSRF.
- External IdP (Keycloak): out of scope for a single-box deployment; the JWT layer is the seam to add OIDC later.
