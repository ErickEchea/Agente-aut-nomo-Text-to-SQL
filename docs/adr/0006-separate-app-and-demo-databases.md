# ADR-0006 — Separate app and demo databases

- Status: Accepted
- Date: 2026-11-20

## Context
The app needs a read/write store (users, runs, embeddings, audit). The retail demo is a *target* that the agent
queries read-only. Mixing them in one database means a single misconfigured grant could expose app tables
(password hashes, encrypted credentials) to agent-generated SQL.

## Decision
- **app-db**: `pgvector/pgvector:0.8.7-pg18-trixie`, database `nexus_app`, role `nexus_app` (owner of its schema),
  extensions `vector`, `pg_trgm`, `unaccent`. Schema managed by Alembic.
- **demo-db**: `postgres:18`, database `retail`, schema `retail`, owner role `retail_owner` (used only by the seed
  job), read role `nexus_reader` (ADR-0005). No credentials for app-db exist in the demo-db container and vice versa.
- The demo DB is registered at startup as a normal *connection* (encrypted credentials, schema indexing), so the
  same code path serves user-added PostgreSQL/MySQL/SQLite sources.

## Alternatives considered
- Same cluster, two databases: cheaper (one container) but shares superuser, `pg_hba`, and resource limits.
- Same database, two schemas: rejected for the reason above.

## Consequences
- One extra container (~100 MB RAM idle).
- Integration tests spin up both via Testcontainers.
