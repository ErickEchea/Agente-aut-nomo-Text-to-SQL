# PROGRESS

Phase plan and exit criteria: [`docs/ROADMAP.md`](docs/ROADMAP.md).

## Status

| Phase | State |
|---|---|
| 0 — Plan, ADRs, structure | ✅ Done (2026-11-20) |
| 1 — Infra, demo DB, read-only role | ✅ Done (2026-11-20) |
| 2 — Agent core + security | ✅ Done (2026-11-20) |
| 3 — RAG + memory | ✅ Done (2026-11-20) |
| 4 — Frontend + design system | ✅ Done (2026-11-21) |
| 5 — Explainability, optimization, multi-DB | ✅ Done (2026-11-21) |
| 6 — Benchmark + default model | ✅ Done (2026-11-22) — awaiting go-ahead for Phase 7 |
| 7 — Hardening + docs | ⏳ |

## Phase 6 — 2026-11-22

### Exit criteria
- ✅ **At least 120 golden questions**:
  - 126 Spanish questions: 40 easy, 40 medium, 31 hard (one is a follow-up asked after its earlier turn)
    and 15 ambiguous.
  - Every gold query follows the glossary and passes the agent's validator (unit test). Every one also
    runs read-only on PostgreSQL (integration test).
  - The answers are frozen with SQL hashes and the dataset version.
- ✅ **Runner** (`nexus-bench`, `make bench`):
  - Same graph, source runtime, validator and read-only role as the API.
  - Questions are isolated, and verified examples are checked for leakage first.
  - Outputs: JSON records, the app DB, and the report.
- ✅ **Report**: [docs/benchmark.md](docs/benchmark.md), generated from `bench/results/`.
- ✅ **Benchmark page**:
  - The chosen model, and the rule that chose it.
  - An accuracy-versus-p95 chart with the selection band.
  - A comparison table with eligibility.
  - Every question's outcome and SQL.
- ✅ **CI subset**:
  - `.github/workflows/bench.yml` runs the full stack on the CPU profile, 15 questions on
    `qwen2.5-coder:3b`, with a gate at 0.6.
  - Calibrated against 11/15 = 0.733, reproduced exactly in a second run.
- ✅ **Superseding ADR**: [ADR-0022](docs/adr/0022-default-model-from-benchmark.md). The default stays
  `qwen2.5-coder:7b` (71.4 %), now as a measured decision.
- ✅ Tests and checks:
  - Backend: 619 tests (non-LLM), 95 % coverage on the gated packages.
  - Frontend: 110 Vitest tests and 26 Playwright tests (`make e2e`).
  - `make e2e-agent` passes with the selected model.
  - ruff, mypy `--strict`, ESLint and `tsc` are clean, and `make up` is healthy.

### Results (final run, identical code for all)
| Configuration | Accuracy | Hard | p95 | Reference conversation |
|---|---|---|---|---|
| `qwen3:8b`, reasoning off | 72.2 % | 58.1 % | 43.3 s | ✗ |
| **`qwen2.5-coder:7b`** | **71.4 %** | 38.7 % | 42.8 s | ✓ (selected) |
| `gemma4:e4b-it-qat`, reasoning off | 71.4 % | 38.7 % | 26.4 s | ✗ |
| routed qwen3 + coder | 69.0 % | 35.5 % | 58.0 s | ✓ |
| `qwen2.5-coder:3b` (CPU) | 57.1 % | 22.6 % | 32.0 s | ✗ |

### Done
- **Data-driven selection**, encoded in `nexus.bench.metrics`:
  - Only configurations that answer the reference conversation (h001 plus its follow-up h031) are
    eligible.
  - Among them, the highest accuracy wins; within 2 points of it, the lowest p95.
- **Model options**:
  - A reasoning toggle (`NEXUS_LLM_THINK`) for models that think by default.
  - Per-node routing as configuration (`NEXUS_LLM_MODEL_<NODE>`, plus `NEXUS_LLM_EXTRA_MODELS`, which
    ollama-init pulls).
  - Both are wired through compose and `.env.example`.
- **`SourceRuntime.agent_context()`**: the API and the benchmark now build the agent's context the same
  way.
- **API**: `GET /api/benchmark` and `/api/benchmark/runs/{id}`, with migration `d29f69672965`. A test
  checks that migration against the models.

### Bugs found by the benchmark and fixed
- **Validator crash on tokenizer errors**: an unterminated string in model SQL raised `TokenError`,
  which crashed the run instead of being repaired. The validator now fails closed on any sqlglot error
  (`parse_error`); two cases were added to the attack suite.
- **Truncated plan JSON crashed the run**: the plan node now falls back to a single step (unit test).
- **The first selection was reversed by the acceptance test**:
  - `gemma4` would have won the latency tie-break, but it never splits the reference question.
  - `qwen3:8b` drops the revenue figure in the follow-up.
  - Both fail `make e2e-agent`, so the eligibility gate was added and the benchmark was re-run on
    identical code.
- **Git Bash rewrote `./bench:/app/bench` volume specs**: `MSYS_NO_PATHCONV=1` in `BENCH_RUN`.

### Known issues / limitations
- **Accuracy is about 71 %; hard questions about 39 %.** Recurring failures:
  - `LIMIT 1` added to "¿Cuál es el … promedio por …?";
  - only one part of a ratio computed;
  - filters dropped;
  - returns exclusion missing after the repairs run out.
  These are documented in ADR-0022 as input for prompt and glossary work. The PostgreSQL prompt is
  pinned by hash, so any such change must be re-benchmarked.
- **Sample size**: 126 questions give about ±8 points at 95 %. The top three configurations are
  statistically tied on accuracy.
- **CI subset on CPU**: the first GitHub Actions run (run 45071212312, about 30 minutes) passed the 0.6
  gate on CPU. The exact CPU accuracy is in that run's `bench-ci-results` artifact, which is readable
  only when signed in to GitHub.
- **CPU profile**: `qwen2.5-coder:3b` reaches 57 % (53 % on ambiguous questions); GPU is the supported
  profile.

## Phase 5 — 2026-11-21

### Exit criteria
- ✅ **Integration tests against MySQL and SQLite**:
  - `test_multidb_mysql.py` (7 tests, `mysql:8.4.9` via Testcontainers) and `test_multidb_sqlite.py`
    (9 tests) run the real executor, introspection, probe and optimizer on each engine.
  - They also check the read-only guarantees: DDL is refused even for a user with write grants (MySQL
    1792), and `mode=ro` plus `query_only` block writes on SQLite.
  - The API test suite registers a SQLite source, asks a question and gets a SQLite-dialect query.
- ✅ **The optimizer finds the planted missing index**:
  - On the full-scale demo, "¿Cuántas unidades de Agua mineral 1.5 L se vendieron en total?" gets the
    suggestion `detalle_ventas(producto_id)`, with the estimated cost going from 7 521.5 to 3 135.2
    (−58 %, HypoPG).
  - `test_optimizer_pg.py` asserts the same at test scale (252.8 → 139.0). On SQLite, the same table is
    reported as a full scan with the same suggestion.
- ✅ Tests and checks:
  - Backend: 546 tests (non-LLM), 94 % coverage on the gated packages.
  - Frontend: 105 Vitest tests. `make e2e` has 22 Playwright tests: axe on every screen, and the SQLite
    source lifecycle (desktop only).
  - `make e2e-agent` passes with the new Explanation/Optimization assertions.
  - ruff, mypy `--strict`, ESLint and `tsc` are clean, and `make up` is healthy with the HypoPG
    demo image.

### Done
- **Clause-by-clause explanation** (`nexus.sql.annotate`, ADR-0021):
  - Deterministic; each clause has exact spans.
  - Descriptions come from the catalog's comments; glossary rules are shown only when the clause
    satisfies them.
  - Available in es/en.
  - In the UI, hovering or focusing a clause card highlights its span in the Shiki-rendered SQL, and
    hovering the SQL selects the clause.
- **Optimizer** (`nexus.sql.optimizer`):
  - Reads EXPLAIN output on PostgreSQL, MySQL and SQLite and flags full scans of large tables.
  - Finds candidate columns from the AST and existing indexes.
  - On PostgreSQL, measures each candidate with HypoPG hypothetical indexes.
  - The UI shows findings, the DDL with a copy button, and before/after cost bars. NEXUS never creates
    the index.
- **Data sources**:
  - The `datasources` package: dialect profiles, error classification per engine, introspection,
    `ConnectionRegistry` with lazy per-source runtimes, and a probe that checks version, tables and write
    privileges.
  - Migration `adc942f4f943` adds `data_connections` and `connection_key` on conversations and runs.
  - Each conversation is pinned to its source.
- **Credentials**:
  - Fernet `MultiFernet` with rotation (`NEXUS_CREDENTIALS_KEYS`, `make rotate-keys`).
  - Writable credentials are rejected unless an admin acknowledges them (`409`).
  - Secrets are never returned by the API.
- **Connections screen**:
  - Source list with index state and polling while indexing; source detail.
  - Admin add/test/re-index/delete dialog: PostgreSQL, MySQL, SQLite file picker, optional
    reference date, PII columns.
  - A source picker in the query bar, and the active source in the header badge.
- **Demo assets**:
  - `infra/postgres/demo-image`: PostgreSQL 18.7 + HypoPG 1.4.5, with the extension in schema `hypopg`
    and usage granted to `nexus_reader` by a one-shot service.
  - `make sqlite-demo` exports the retail data to SQLite with the same comments and indexes (and the
    same missing one).
- **Docs**:
  - ADR-0021 is new.
  - Implementation notes were added to ADR-0012 and ADR-0013.
  - ARCHITECTURE and the READMEs are updated.
  - Screenshots are in `docs/screenshots/phase5/`.

### Bugs found and fixed this phase
- **Prompt drift on PostgreSQL** (found by `make e2e-agent`): making the SQL rules a per-engine template
  added one PostgreSQL tip (`date_trunc`) and moved a line break. With greedy decoding, the 7B model
  then wrote a branch-revenue query with a grouping error (42803), and three repairs returned the same
  SQL. The PostgreSQL rules are byte-identical to the validated Phase 4 prompt again, and a unit test
  pins them by hash. MySQL and SQLite keep their own tips.
- **MySQL read-only gap**: `START TRANSACTION READ ONLY` does not stop DDL, because DDL implicitly
  commits and then runs. The session is now also `transaction_read_only = ON` (in `init_command` and in
  the executor). A regression test uses a user with write grants (ADR-0013).
- **PostgreSQL index introspection**: SQLAlchemy's inspector calls `set_config`, which is revoked from
  `nexus_reader`. Indexes are now read with a direct `pg_index` query.
- **HypoPG state leak**: hypothetical indexes survive `ROLLBACK`. The pooled connection is now
  invalidated after each measurement, and the validator denies every `hypopg_*` function in generated
  SQL.
- **sqlglot 30**: the FROM argument is now `from_`; the annotator was updated. `UNION` branches and
  binary `IS NULL` nodes had no descriptions; both are fixed.
- **Accessibility** (found by axe in the `@llm` run): the annotated SQL `<pre>` and the suggested-DDL
  `<code>` scroll horizontally but could not be focused from the keyboard. Both are now focusable, and
  the SQL has an accessible name.
- **Annotation text**: column comments were cut at "p. ej." ("nombre de la categoría, p"). Sentence
  detection now ignores abbreviations and decimals (unit-tested).
- **Fallback summary**: when the grounded summary fails its number check, the deterministic fallback
  used to read "pregunta → 10 filas; primera: …" in Spanish only. It now reads as a sentence in the
  user's locale.

### Known issues / limitations
- **MySQL and SQLite optimizer**: no before/after cost. MySQL gives only a total `query_cost`; SQLite
  has no cost model. The UI says so (ADR-0021).
- **External PostgreSQL without HypoPG**: suggestions are shown without measured costs.
- **Live-model QA**: MySQL was verified through integration tests with the fake LLM and through the
  live probe. A browser run against a live MySQL server was not done, because no MySQL server runs on
  this machine outside Testcontainers.
- **Retrieval for new sources**: a new source is indexed without glossary terms or verified examples.
  The glossary is retail-specific (ADR-0018), and examples accumulate from user feedback.

## Phase 4 — 2026-11-21

### Exit criteria
- ✅ **Playwright e2e of the reference question** in the browser with the real model (`make e2e-agent`):
  - The timeline streams live.
  - The answer is correct: top-5 starting with Agua mineral 1.5 L, and Samborondón $299,672.19.
  - The figures are verified and the «último trimestre» assumption is shown.
  - The table, chart (canvas), SQL and optimization tabs work.
  - Pinning to a new dashboard shows the chart there.
  - Warm run: 45 s.
  - The API e2e (reference + follow-up) still passes.
- ✅ **axe clean**: WCAG 2.2 A/AA on every screen in dark and light at 1280 px and 375 px, plus the answered
  workspace and a dashboard. It runs inside `make e2e` (20 tests).
- ✅ **Screenshots reviewed and committed**: `docs/screenshots/phase4/` holds 42 PNGs. Every screen is in
  dark/light × desktop/375 px, plus the live timeline, the answer, the SQL tab and a dashboard.
- ✅ Tests and checks:
  - Backend: 499 tests (non-LLM), 94 % coverage on the gated packages (93 % overall).
  - Frontend: 105 Vitest tests.
  - ruff, mypy `--strict`, ESLint (type-checked, i18n literal-string rule) and `tsc` are clean.
  - `make up` is healthy.

### Done
- **Design system first**: `docs/DESIGN.md` and `tokens.css`.
  - Dark default, plus a selected light palette.
  - Fonts: Bricolage Grotesque (display), IBM Plex Sans (UI), JetBrains Mono (SQL and figures).
  - The categorical data palette is validated with the dataviz CVD/contrast checker on our own surfaces.
  - Tests enforce AA contrast for every text/surface pair and fail on any raw hex color outside the tokens.
- **Screens**:
  - Login.
  - Workspace: query bar, example questions, conversation turns with follow-ups and clarification options.
  - Live agent timeline: status, live timer, tokens, expandable node output, highlighted SQL, red/green
    repair diff.
  - Result tabs: virtualized table with sort/filter/CSV, ECharts with PNG export, SQL, explanation, and
    optimization (marked as Phase 5).
  - KPI cards with hierarchy, feedback with "mark SQL as correct", pin to dashboard.
  - Dashboards, history and memory, connections, benchmark (honest empty state), audit (admin), settings,
    and the Ctrl/⌘ K palette.
- **Backend support**:
  - Typed `RunResult` in the OpenAPI contract, with an OpenAPI snapshot, generated TS types and a drift test
    (`make api-types`).
  - Dashboards API (private or shared; analysts and admins pin; migration `f574d0c093cf`).
  - `GET /api/connections`, with planner row estimates: the seed loader now runs `ANALYZE`.
  - `nexus-admin create-user --if-missing` and `make e2e-user` for the Playwright account.
- **Engineering**:
  - Access token in memory; refreshes are coalesced and sent with `keepalive`.
  - SSE over fetch with `Last-Event-ID` resume and zod-validated events.
  - Lazy ECharts and secondary routes; the workspace entry is ~270 kB gzip.
  - CSP-safe Shiki and fonts.
  - Decisions are recorded in ADR-0020.

### Bugs found by visual QA and fixed this phase
- **Agent**:
  - The planner sometimes answered with MySQL SQL instead of sub-questions, and the run failed after
    three repairs. A deterministic guard now discards SQL-shaped plans (ADR-0020 §15) and has a unit test.
  - The chart for "top 5 products" plotted `producto_id`. Charts now never plot identifiers and prefer the
    measure the question names (§16), with a unit test.
- **Session**: a navigation during the boot-time refresh aborted the request after the server had rotated
  the token, so the next refresh tripped reuse detection and logged the user out. Fixed with `keepalive`
  (§6). A stress repro went from losing the session on the first aborted refresh to never losing it.
- **Layout**:
  - Wide SQL lines pushed the answer under the timeline rail, and the whole answer overflowed at 375 px.
    Grid tracks are now `minmax(0, 1fr)`.
  - The workspace scrolled `#main` instead of the conversation pane.
- **Accessibility** (found by axe):
  - ghosted timeline steps below AA contrast;
  - the account button's name not matching its visible initials;
  - non-focusable scrollable regions;
  - icon-only buttons without names at 375 px.
- **CSP**: Vite inlined small fonts as `data:` URIs, which `font-src 'self'` blocks (`assetsInlineLimit: 0`).
- **Palette UX**: typing a screen name and pressing Enter asked the agent instead of navigating. "Ask the
  agent" now always ranks last.

### Known issues / limitations
- **Bundle size**: ~270 kB gzip for the workspace entry, with ECharts lazy (~190 kB gzip). Acceptable for an
  authenticated internal tool. A budget is set at 900 kB minified.
- **Benchmark**: the page is an honest empty state until Phase 6. The optimization tab and multi-connection
  management are Phase 5.
- **Shared dashboards**: they show the owner's run results to every user. That is by design (sharing is an
  explicit owner action) and documented in ADR-0020.
- **Frontend design skill**: no dedicated skill for application UI was available in this environment. The
  dataviz skill guided the chart palette, marks and interaction, and every screen was reviewed through
  Playwright screenshots.

## Phase 3 — 2026-11-20

### Exit criteria
- ✅ **Retrieval**: 32-question evaluation, `qwen3-embedding:0.6b` with hybrid search. recall@5 = 0.968, and
  **all needed tables were in context for 32/32 questions** (1.000), with about 4.5 of 10 tables sent.
  Hybrid beats dense-only (0.938) and lexical-only (0.969). Full table: `docs/retrieval-eval.md`.
- ✅ **Follow-up**: "¿Y en el trimestre anterior?" in the same conversation resolves to Q2 2026 and returns the
  exact expected top-5 and branch (Guayaquil Norte - Alborada, $291,168.77). Passed in 3/3 live runs, and the
  reference question still passes in 3/3 (`make e2e-agent`).
- ✅ 489 tests (non-LLM). Coverage is 90 % over agent/security/sql/rag/memory; the gated packages are ≥ 85 %.
  ruff and mypy `--strict` are clean.

### Done
- **Schema RAG**: document builder (tables, columns with non-PII sample values, glossary terms, verified
  examples), pgvector + Spanish full-text + trigram store, RRF fusion, glossary-forced tables, value linking,
  Steiner join paths, fingerprinted index rebuilt at startup only when something changed, graceful degradation.
- **Nodes**: `retrieve_schema`; `visualize` (rules, model tie-break only between rule candidates, validated
  ECharts spec, KPI cards); `explain` (grounded summary, retry naming invented figures, deterministic
  fallback); `remember`.
- **Memory**: conversation turns with resolved periods (follow-ups), frequent questions, preferences
  (locale used by `explain`), feedback, and verified examples indexed immediately (`POST /api/runs/{id}/feedback`).
- **Glossary v2**: complete `requires` tables for revenue, units, average ticket, gross margin and return rate;
  entity terms with `maps_to`.
- `make eval-retrieval` (`nexus-eval-retrieval`) compares embedding models and template variants.

### Bugs found and fixed this phase
- `pg_constraint.contype` is `"char"`: asyncpg returned bytes, so every primary key was treated as a
  foreign key with target `None`. Since Phase 2 the prompt had carried bogus `FK→None.None` annotations.
  Now cast to text, with an integration test of introspection that did not exist before.
- JSON/JSONB values were serialized with Python `repr()` instead of JSON.
- Value linking missed values followed by punctuation ("¿…la Costa?").

### Known issues / limitations
- The retrieval evaluation set was also used to diagnose the forced-table rules. The Phase 6 golden set is
  the held-out check.
- Cold start: the first question after boot pays model loading (~12 s in `understand`, ~6 s for the first
  embedding). Warm runs take ~20 s for the two-part question on the shared laptop GPU.

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
