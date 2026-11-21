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

## Implementation notes (Phase 5, 2026-11-21)
- **Registry.** `nexus.datasources.registry.ConnectionRegistry` lazily builds one `SourceRuntime` per
  connection. A runtime holds the engine, executor, catalog, dialect-aware validator policy, PII masker,
  retriever and samples. Each conversation is pinned to the source it started with, and follow-ups
  reuse that source. Prompts receive the source's `DialectProfile`: its date literals, function hints
  and engine-specific SQL tips. PostgreSQL has no extra tips: its rules stay byte-identical to the
  prompt validated end to end, and a unit test pins them by hash. One added line had been enough to
  change the 7B model's greedy output on the reference question.
- **MySQL finding.** `START TRANSACTION READ ONLY` alone does **not** stop DDL, because DDL commits the
  open transaction implicitly and then runs. The executor therefore also sets
  `SET SESSION transaction_read_only = ON`, and the engine's `init_command` does the same.
  `test_multidb_mysql.py` runs `CREATE TABLE` with a user that has write grants and asserts error 1792.
- **PostgreSQL introspection.** SQLAlchemy's PostgreSQL inspector calls `set_config`, which the
  `nexus_reader` role is not allowed to run. Index introspection therefore uses its own `pg_index`
  query.
- **Error classes.** `classify_error` maps each engine's errors to codes the repair loop can act on:
  SQLSTATE for PostgreSQL, `MY<errno>` for MySQL (1054 and 1064 can be repaired; 3024 is a timeout) and
  `SQLITE_*` for SQLite.
- **Optimizer detail.** ADR-0021 covers it. The optimizer gives before/after costs on PostgreSQL through
  HypoPG, a total plan cost on MySQL, and plan shape only on SQLite.
