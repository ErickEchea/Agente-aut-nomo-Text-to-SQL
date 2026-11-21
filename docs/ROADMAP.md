# Roadmap — phases and exit criteria

Every phase closes only when: all tests pass, lint + typecheck are clean, `docker compose up` is healthy for
the services that exist so far, and `PROGRESS.md` is updated.

## Phase 0 — Plan ✅
CLAUDE.md, ARCHITECTURE.md (Mermaid), 16 ADRs, roadmap, PROGRESS.md, repo hygiene files.

## Phase 1 — Infrastructure, demo DB, read-only role ✅
- `docker-compose.yml` (+ `docker-compose.gpu.yml`): app-db, demo-db, ollama, ollama-init, demo-seed, backend,
  frontend — each with a healthcheck. Backend at this phase: settings, structured logging with `request_id`,
  `/api/health/live` and `/api/health/ready` (real checks of both DBs and Ollama models). Frontend at this phase:
  production nginx image serving the Vite build of a minimal shell (replaced in Phase 4).
- `infra/postgres/demo/`: roles (`retail_owner`, `nexus_reader`) with the grants of ADR-0005.
- `data/retail/schema.sql` with `COMMENT ON` for every table/column; generator `nexus.demo` — seeded,
  2 years (2024-11-01 → 2026-10-31), seasonality, trend, planted anomalies, ≈500k `detalle_ventas`, loaded with
  `COPY`; `data/glossary.yaml`.
- Makefile, `.env.example`, pre-commit config, install `make` on Windows.
- **Exit**: `make up` from scratch → all healthy; row counts and seasonality checks pass (tests over the generator,
  deterministic checksum with the fixed seed); `nexus_reader` provably cannot write (integration test).

## Phase 2 — Agent core + security suite ✅
- `LLMProvider` + `OllamaProvider` (structured output, usage), validator (ADR-0005), executor (read-only txn,
  timeouts, row cap, separate pool), LangGraph graph with `understand → generate_sql → validate → execute →
  repair → verify_results` plus `plan` (moved up from Phase 3: the reference question is compound) and a
  deterministic `respond` (the grounded LLM `explain` stays in Phase 3). Retrieval sends the full schema
  until Phase 3. Temporal resolver, SSE endpoints,
  JWT auth + RBAC + rate limit + audit log + PII masking, Alembic migrations.
- Attack suite ≥ 40 cases in three modes.
- **Exit**: reference question answered via API (curl SSE) with correct SQL; attack suite 100 % blocked; coverage
  gates met.

## Phase 3 — RAG, glossary, verified examples, memory ✅
- Indexer + hybrid retriever + join-path finder; `plan`, `visualize`, `explain` (grounded), `remember` nodes;
  short/long-term memory; feedback → verified examples; embedding-model comparison (recall@5).
- **Exit**: retrieval recall@5 ≥ target on golden-derived set; follow-up question test passes.

## Phase 4 — Frontend and design system ✅
- `docs/DESIGN.md` + tokens first; all screens (login, workspace + Ctrl/Cmd+K, results tabs, KPI cards,
  dashboards, history/memory, connections, benchmark, audit, settings); live agent timeline with SQL highlighting
  and repair diffs; virtualized table with CSV export; ECharts with PNG export; i18n es/en; a11y; responsive.
- **Exit**: Playwright e2e of the reference question; axe clean; screenshots of every screen (dark/light,
  desktop/375 px) reviewed and committed under `docs/screenshots/`.

## Phase 5 — Explainability, optimization, multi-DB ✅
- Clause-by-clause SQL explanation linked to highlighted spans; EXPLAIN (FORMAT JSON) analyzer with before/after
  cost; connection manager for PostgreSQL/MySQL/SQLite with encrypted credentials, test, and indexing.
- **Exit**: integration tests against MySQL and SQLite; optimizer finds the planted missing-index case.

## Phase 6 — Benchmark and default model
- ≥ 120 golden questions; runner; report; Benchmark page; CI subset; superseding ADR with the chosen default.

## Phase 7 — Hardening and documentation
- Security review pass, dependency audit, load sanity check, README (≤ 10 min quickstart), demo GIF, architecture
  diagram, benchmark results; CI green end-to-end.
