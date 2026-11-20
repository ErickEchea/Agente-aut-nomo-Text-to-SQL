# PROGRESS

Phase plan and exit criteria: [`docs/ROADMAP.md`](docs/ROADMAP.md).

## Status

| Phase | State |
|---|---|
| 0 — Plan, ADRs, structure | ✅ Done (2026-11-20) |
| 1 — Infra, demo DB, read-only role | ✅ Done (2026-11-20) |
| 2 — Agent core + security | ✅ Done (2026-11-20) — awaiting go-ahead for Phase 3 |
| 3 — RAG + memory | ⏳ |
| 4 — Frontend + design system | ⏳ |
| 5 — Explainability, optimization, multi-DB | ⏳ |
| 6 — Benchmark + default model | ⏳ |
| 7 — Hardening + docs | ⏳ |

## Phase 2 — 2026-11-20

### Exit criteria
- ✅ **Reference question answered end to end** through nginx → JWT → `POST /api/runs` → SSE, with the real
  model (`qwen2.5-coder:7b`, GPU): exact top-5 products and Samborondón at $299,672.19. 3/3 consecutive runs
  passed (`make e2e-agent`), ~20 s each with the GPU shared with other software.
- ✅ **Attack suite fully blocked**: 62 SQL attacks in 3 modes, 9 benign controls, 10 prompt attacks + 11
  false-positive controls (`make test-security`, 284 tests).
- ✅ Coverage gate: **94 %** on `agent/`, `security/`, `sql/` (`make coverage`, enforced in CI).
- ✅ ruff, mypy `--strict`, ESLint, `tsc` clean; `make up` healthy (now with a `migrate` job).

### Done
- **Agent (LangGraph)**: `understand` (deterministic guard first, then model) → `plan` → `resolve_time` →
  `generate_sql` → `validate` → `execute` → `verify_results` ⇄ `repair` (≤ 3) → `respond`. Typed state, injected
  runtime context, pure routing functions tested edge by edge, every node instrumented (SSE event + log span
  with duration and tokens).
- **LLM layer**: `LLMProvider` protocol + `OllamaProvider` (JSON-schema structured outputs, temperature 0, fixed
  seed, token usage); per-node model routing hook.
- **SQL safety**: SQLGlot AST validator (deny-by-default functions, table/schema allowlist, forced LIMIT,
  comment stripping); read-only executor that only accepts `ValidatedSQL`; advisory locks revoked from the
  reader after the suite found them executable (ADR-0005 notes).
- **Deterministic guards (ADR-0018)**: question guard before the model; glossary `requires` rules checked on
  the AST in `verify_results` (caught the model omitting the returns exclusion, then repaired).
- **Temporal resolver** (es/en, `as_of`), PII masking traced through aliases/CTEs, prompt data blocks that
  cannot be closed by injected text.
- **API**: JWT access (15 min) + rotating refresh cookie with reuse detection; roles admin/analyst/viewer;
  token-bucket rate limits (login per IP and per email, runs per user, one concurrent run per user);
  `POST /api/runs`, `GET /api/runs[/{id}]`, `GET /api/runs/{id}/events` (SSE, `Last-Event-ID` replay),
  `DELETE /api/runs/{id}`, `GET /api/audit` (admin); audit log of logins and every SQL attempt.
- **Persistence**: Alembic migrations (users, refresh_tokens, conversations, runs, run_events, audit_log);
  `nexus-migrate`, `nexus-admin create-user`; bootstrap admin from `.env`.

### Known issues / limitations
- Latency: ~20 s for the two-part reference question on the reference laptop while another GPU-heavy
  application (a game) was running; the GPU delivered ~18 tok/s. To be measured cleanly in Phase 6.
- The answer text is a deterministic summary of the results; the grounded LLM explanation (ADR-0014),
  `visualize`, schema RAG and long-term memory are Phase 3 (short-term history is already passed to
  `understand`).
- Single-replica assumptions remain for rate limiting, the concurrent-run lock and SSE fan-out.
- `uvicorn --forwarded-allow-ips *`: the backend port is published on loopback only and nginx overwrites
  `X-Forwarded-For`; anyone with shell access to the host could still spoof a client IP.

## Phase 1 — 2026-11-20

### Done
- **Compose stack** (`docker-compose.yml` + `docker-compose.gpu.yml`): `app-db` (pgvector pg18), `demo-db`
  (postgres 18.7), `demo-seed` (one-shot), `ollama` 0.40.16, `ollama-init` (one-shot model pull), `backend`,
  `frontend` (nginx). Healthchecks on every long-running service; DB checks use TCP so they stay red during init.
  `make up` auto-selects the GPU profile (verified: RTX 5060 visible inside containers) and the matching model.
- **Secrets**: `make env` creates `.env` from `.env.example` with a fresh 256-bit secret per password.
- **Demo DB** (ADR-0017, Ecuador, USD): 10 tables with `COMMENT ON` for every table and column (tested),
  13 FKs, CHECK constraints including `total = subtotal − descuento_total + iva`. Generator `nexus.demo`:
  vectorized numpy, fixed seed, ~4 s for 499,485 `detalle_ventas` / 196,091 `ventas`; checksum
  `7ce93227…` is identical on Windows and inside the Linux container. Ecuadorian calendar (Carnaval from Easter,
  décimo tercer/cuarto sueldo by region, Sierra vs Costa school seasons, Black Friday, Día de la Madre,
  World Cup 2026), planted anomalies (stock-out, returns spike, closure, new branch, outlier order, voided
  tickets, missing index). Seed job is idempotent (checksum stored in `retail_meta`, invisible to the reader).
- **Read-only role** `nexus_reader` (ADR-0005 layer B): SELECT on `retail` only, read-only by default,
  `statement_timeout 15s`, `lock_timeout 2s`, no EXECUTE on `pg_sleep*`, `set_config`, `pg_terminate_backend`,
  `pg_cancel_backend`; no CONNECT on `postgres`/`template1`. Integration tests prove every write/DDL fails
  **even after** the session flips `default_transaction_read_only = off`.
- **Backend**: pydantic-settings config (fail-fast, no wildcard CORS), structlog JSON with secret redaction,
  pure-ASGI `request_id` middleware (SSE-safe), `/api/health/live` and `/api/health/ready` (app DB extensions,
  demo DB reachable *and* read-only, Ollama models pulled — readiness goes red if the API is ever pointed at a
  writable role).
- **Frontend**: React 19 + TS 6 strict + Vite 8 status page backed by `/api/health/ready`, es/en i18n,
  TanStack Query polling; nginx with SSE-safe `/api` proxy and security headers (CSP, frame-ancestors none).
- **Quality**: backend 56 unit + 43 integration tests (Testcontainers, same init scripts as compose), 97 %
  line coverage, pytest warnings are errors; ruff + mypy `--strict` clean. Frontend: 3 Vitest tests, ESLint
  (strict type-checked), `tsc -b`, production build; Playwright e2e against the running stack with screenshots
  in `docs/screenshots/phase1/`. `.pre-commit-config.yaml`, `.github/workflows/ci.yml`.
- Tooling installed: GNU make 4.4 (winget `ezwinports.make`), GitHub CLI 2.105, uv upgraded to 0.13.9.

- **CI green on GitHub** (backend incl. Testcontainers on Linux, frontend, Docker images + compose config).
  First run failed because `astral-sh/setup-uv` publishes no floating `v10` tag; pinned to `v10.4.0`.
- Reference answer established on the live DB (as `nexus_reader`): Q3 2026 top-5 by units = Agua mineral
  1.5 L, Pollo entero Mr. Pollo, Leche Toni, Leche Parmalat, Aceite La Favorita; top branch by revenue =
  Samborondón ($299,672.19). This is the Phase 2 end-to-end target.

### Known issues / limitations
- `gh` is installed but not authenticated (needs `gh auth login` by the user); CI status is read through the
  public GitHub API instead.
- `make` is installed but the current shell's PATH only picks it up after a new terminal session.
- GPU default model (`qwen2.5-coder:7b`) is **provisional** until the Phase 6 benchmark (ADR-0003).
- Inventory snapshots do not scale with `NEXUS_DEMO_SCALE` (branch × product × month grid, ~229k rows).
- The host's own Ollama (0.24, auto-started during the survey) keeps running on 11434; the stack does not use it.

## Phase 0 — 2026-11-20

### Done
- Environment survey: Windows 11, Docker 29.9 / Compose v5.7, Python 3.11 + 3.14 (host), Node 24,
  npm 11, ffmpeg 8.1, NVIDIA RTX 5060 Laptop (8 GB VRAM, driver 621.24), host Ollama 0.24 with `qwen3:8b` cached.
- Verified current versions of all planned dependencies, Docker images and Ollama models (ADR-0002, ADR-0003).
- `CLAUDE.md`, `docs/ARCHITECTURE.md`, `docs/ROADMAP.md`, ADR-0001…0017, repo hygiene files, area READMEs.

### Known issues / risks (carried forward)
- **8 GB VRAM** limits candidates to ≤ ~8B models; the newest large families (qwen3.6/3.8, gemma4 26B+,
  qwen3-coder 30B) are documented but not defaults. Hard-question accuracy will reflect that.
- **TypeScript 7** cannot be used yet: typescript-eslint 8.73 supports `<6.1`. Pinned to 6.0.3.
- Host ports 5432 (local Postgres) and 11434 (host Ollama) are occupied; the stack uses alternative host ports.
- Single-replica assumptions: in-process rate limiter (ADR-0011) and SSE fan-out queue (ADR-0009).
