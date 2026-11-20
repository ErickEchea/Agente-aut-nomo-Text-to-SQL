# ADR-0011 — Rate limiting

- Status: Accepted
- Date: 2026-11-20

## Context
Agent runs are expensive (GPU time). Login must resist brute force. `slowapi` (0.1.10) is stale, and we do not
want Redis only for this.

## Decision
- Own ASGI middleware + dependency implementing a **token bucket**, keyed by `(user_id | client_ip, route_class)`:
  `auth` (5/min per IP + per email), `run` (e.g. 20/min, 1 concurrent run per user), `default` (120/min).
- Storage: in-process (single replica). Interface `RateLimitStore` so a Postgres- or Redis-backed store can replace
  it without touching routes.
- Responses: `429` with `Retry-After` and `RateLimit-*` headers (IETF draft fields).

## Consequences
- Limits reset on restart and are per-process — acceptable for the single-replica deployment, documented as a
  known limitation in PROGRESS.md.
