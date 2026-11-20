# infra

- `postgres/app/` — app-db init (extensions `vector`, `pg_trgm`, `unaccent`; app role).
- `postgres/demo/` — demo-db init (`retail_owner`, read-only `nexus_reader`, grants per ADR-0005).
- `nginx/` — frontend server config (SPA routing, `/api` proxy with SSE buffering disabled, security headers).

Populated in Phase 1.
