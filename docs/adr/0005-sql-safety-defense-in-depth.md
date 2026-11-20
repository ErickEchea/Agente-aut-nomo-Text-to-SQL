# ADR-0005 — SQL safety: defense in depth

- Status: Accepted
- Date: 2026-11-20

## Context
The LLM produces SQL from untrusted input (user questions and database contents). A single control is not
acceptable: validators have parser gaps, and roles can be misconfigured. Each layer must block destructive or
exfiltrating SQL **on its own**.

## Decision

### Layer A — AST validation (`nexus.sql.validator`, SQLGlot, never regex)
1. Parse with the connection's dialect, `error_level=RAISE`. Parse failure → reject.
2. Exactly **one** statement.
3. Root must be `exp.Select`, or a set operation (`UNION/INTERSECT/EXCEPT`) of selects, optionally under `WITH`.
4. Walk the entire tree; reject if any node is DML/DDL/command (`Insert`, `Update`, `Delete`, `Merge`, `Create`,
   `Drop`, `Alter`, `TruncateTable`, `Command`, `Copy`, `Grant`, `Set`, `Transaction`, `Commit`, …) — this catches
   modifying CTEs (`WITH x AS (DELETE … RETURNING *)`).
5. Reject `SELECT … INTO`, `FOR UPDATE/SHARE` locking clauses, `CALL`, `LOAD`, `TABLESAMPLE` on system tables.
6. **Functions**: deny-by-default. Known-safe built-ins (aggregates, math, string, date/time, conditional, window,
   casts) are allowed; anything parsed as `exp.Anonymous` must be in a configurable allowlist. An explicit denylist
   (`pg_sleep*`, `pg_read_file`, `pg_read_binary_file`, `pg_ls_dir`, `pg_stat_file`, `lo_*`, `dblink*`,
   `set_config`, `current_setting`, `pg_terminate_backend`, `pg_cancel_backend`, `pg_reload_conf`,
   `pg_advisory_*`, `txid_*`, `query_to_xml`, `xpath`, MySQL `sleep`/`benchmark`/`load_file`, SQLite
   `load_extension`, …) is kept for clear error messages and tests.
7. **Tables**: every `exp.Table` must resolve (after qualifying CTE names out) to an allowed `schema.table` for
   the connection. System catalogs (`pg_catalog`, `information_schema`, `mysql`, `sqlite_master`) are not allowed.
8. **LIMIT**: if the outermost query has no `LIMIT` (or it exceeds the cap), set it to `min(existing, cap)`.
9. Output is re-generated SQL from the AST (`sql(dialect=…)`), so comments and odd whitespace never reach the DB.

### Layer B — Database role
- `nexus_reader`: `LOGIN`, `NOINHERIT`, no superuser/createdb/createrole/replication; `CONNECT` on the demo DB,
  `USAGE` on schema `retail`, `SELECT` on its tables only; `REVOKE ALL ON SCHEMA public`; default privileges for
  future tables; `ALTER ROLE nexus_reader SET default_transaction_read_only = on`,
  `SET statement_timeout = '15s'`, `SET idle_in_transaction_session_timeout = '30s'`.
- `REVOKE EXECUTE` on dangerous functions from `PUBLIC` where the server allows it; extensions like `dblink`
  are not installed.

### Layer C — Session/transaction
- Every execution: `BEGIN READ ONLY` + `SET LOCAL statement_timeout` + `SET LOCAL lock_timeout`; fetch at most
  `cap + 1` rows to detect truncation; rollback always.
- Dedicated connection pool per source, never shared with the app DB pool.

### Layer D — Output
- Optional PII masking per configured column before rows leave the backend; audit log of every execution.

### Verification
- `tests/security/attacks/` holds ≥ 40 cases (YAML) — DROP/DELETE/UPDATE, stacked statements, comment tricks
  (`--`, `/* */`, nested), modifying CTEs, `SELECT INTO`, `COPY … TO PROGRAM`, `CALL`, `pg_sleep`, file reads,
  `set_config`, catalog access, unicode/homoglyph identifiers, case/whitespace evasion, prompt-injection phrases in
  questions ("ignora tus instrucciones…"), and injection payloads stored inside demo-table values.
- The suite runs in three modes: (1) validator only (unit); (2) **validator disabled, read-only role** against real
  Postgres via Testcontainers; (3) validator enabled with a privileged role. Every destructive case must fail in all
  modes; state of the DB is checksummed before/after.

## Consequences
- Some legitimate but exotic SQL (custom functions) needs explicit allowlisting per connection.
- Validation errors are machine-readable codes that feed the `repair` node and humane UI messages.
