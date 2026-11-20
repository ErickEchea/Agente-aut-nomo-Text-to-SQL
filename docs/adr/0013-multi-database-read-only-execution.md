# ADR-0013 — Multi-database read-only execution

- Status: Accepted
- Date: 2026-11-20

## Decision
One async SQLAlchemy engine (own pool) per registered connection; SQLGlot dialect per kind.

| Kind | Driver | Read-only enforcement (in addition to the AST validator) | Timeout | EXPLAIN |
|---|---|---|---|---|
| PostgreSQL | asyncpg | dedicated SELECT-only role + `BEGIN READ ONLY` | `SET LOCAL statement_timeout` | `EXPLAIN (FORMAT JSON)` |
| MySQL 8.x | aiomysql | SELECT-only user (documented GRANT) + `START TRANSACTION READ ONLY` | `MAX_EXECUTION_TIME` hint/session var | `EXPLAIN FORMAT=JSON` |
| SQLite | aiosqlite | `file:…?mode=ro` URI + `PRAGMA query_only = ON` | progress-handler based abort | `EXPLAIN QUERY PLAN` |

- On "test connection" the backend verifies the privileges it got: if a PostgreSQL/MySQL user can write
  (checked via catalog privilege functions, never by attempting a write), the connection is **rejected** unless an
  admin explicitly acknowledges it — in that case the AST validator still applies and the UI shows a warning badge.
- The optimizer (Phase 5) is full-featured for PostgreSQL; for MySQL/SQLite it reports the plan and flags full
  scans, without cost before/after estimates where the engine does not expose them. This is stated in the UI.

## Consequences
- Integration tests run against real PostgreSQL and MySQL containers and a temp SQLite file.
