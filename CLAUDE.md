# CLAUDE.md — NEXUS AI

Autonomous Text-to-SQL agent (Spanish-first business questions → validated read-only SQL → results, chart,
grounded summary), fully local (Ollama). Read `docs/ARCHITECTURE.md` before structural changes and record any new
significant decision as an ADR in `docs/adr/`.

## Non-negotiable rules
1. **No fake code**: no stubs, `TODO`, `pass`-bodies, mocked data or placeholder functions in production code.
   If something cannot be done, say so in `PROGRESS.md`. Mocks/fakes are allowed only under `tests/`.
2. **Phase gate**: do not start the next phase until tests, lint and typecheck are clean, `docker compose up`
   is healthy, and `PROGRESS.md` is updated.
3. **Verify, don't assume**: check current versions/APIs in official docs or registries before pinning or using
   them; run tests; for UI work, take Playwright screenshots and review them.
4. **Safety**: LLM-generated SQL only executes after `nexus.sql.validator` **and** through a read-only
   connection. Never weaken either layer to make a test pass. Never put DB values or user text into a prompt
   outside the delimited data blocks.
5. **Time**: relative dates are resolved by `nexus.agent.temporal`, never by the LLM.
6. **Business rules are data**: metric definitions and their SQL `requires` checks live in
   `data/glossary.yaml` (ADR-0018); prefer adding a rule there over prompt tweaks.
7. Secrets only via environment variables; every new variable goes into `.env.example` with a comment.

## Conventions
- Code, comments, docs, commit messages: **English**. UI strings: Spanish default + English via i18next
  (no literal UI strings in components).
- Conventional Commits, small and scoped: `feat(agent): …`, `fix(sql): …`, `test(security): …`, `docs(adr): …`.
- Python: src layout `backend/src/nexus`, type hints everywhere (`mypy --strict`), Pydantic v2 models at every
  boundary, async I/O, no global mutable state (inject dependencies), structlog for logging (never `print`).
- TypeScript: strict + `noUncheckedIndexedAccess`; API types generated from the backend OpenAPI schema; styling only
  through design tokens (no raw hex colors in components).
- Tests mirror source paths. Unit tests must not need Docker; integration tests use Testcontainers and are marked
  `@pytest.mark.integration`.
- Coverage ≥ 85 % on `nexus/agent`, `nexus/security`, `nexus/sql`.

## Layout
```
backend/   FastAPI + LangGraph agent (package `nexus`)   frontend/  React + Vite app
data/      retail DDL, seeded generator, glossary.yaml   bench/     golden set + runner
infra/     DB init scripts (roles), nginx                 docs/      architecture, design, ADRs, benchmark
```

## Commands (all via `make`, run from Git Bash on Windows)
> Available from the phase noted; `make help` lists what exists.

| Command | What | Phase |
|---|---|---|
| `make env` | Create `.env` with generated secrets (never overwrites) | 1 |
| `make up` / `make down` | Start/stop the full stack (auto GPU/CPU profile), wait for healthchecks | 1 |
| `make seed` / `make reseed` | Load the retail demo data if changed / force reload | 1 |
| `make logs s=backend` | Tail a service | 1 |
| `make test` | Backend unit + frontend unit | 1 |
| `make test-integration` | Testcontainers-based backend tests | 1 |
| `make lint` / `make typecheck` / `make check` | ruff + eslint / mypy + tsc / all of the above + unit tests | 1 |
| `make e2e` | Playwright: every screen, dark/light × 1280/375 px, axe WCAG 2.2 AA, screenshots (stack up; `E2E_ARGS=…` overrides the selection) | 1–4 |
| `make test-security` | Attack suite in all three modes | 2 |
| `make coverage` | All non-LLM tests + 85 % gate on agent/security/sql | 2 |
| `make e2e-agent` | Reference question + follow-up with the real model: API (pytest) and browser (Playwright `@llm`) | 2–4 |
| `make api-types` | Regenerate the OpenAPI snapshot + frontend TS types (a unit test fails if stale) | 4 |
| `make eval-retrieval` | Schema-retrieval metrics per embedding model → `docs/retrieval-eval.md` | 3 |
| `make create-user email=… name=… role=…` | Create analyst/viewer accounts | 2 |
| `make sqlite-demo` | Export the retail demo to `data/sqlite/retail_mini.sqlite` (second engine; `make e2e` builds it if missing) | 5 |
| `make rotate-keys` | Re-encrypt stored connection secrets with the first `NEXUS_CREDENTIALS_KEYS` key | 5 |
| `make bench MODELS="…"` | Run golden-set benchmark, write `docs/benchmark.md` | 6 |

Backend directly: `cd backend && uv run pytest`, `uv run ruff check`, `uv run mypy src`.
Frontend directly: `cd frontend && npm run test`, `npm run lint`, `npm run typecheck`, `npx playwright test`.

## Environment notes (dev machine)
- Windows 11, Git Bash; `core.autocrlf=true` → `.gitattributes` forces LF. Keep it that way.
- Host ports 5432 and 11434 are taken by a local Postgres and the host Ollama app; the stack uses
  55432 (app-db), 55433 (demo-db), 8000 (API), 8080 (web) and does not publish Ollama.
- GPU: RTX 5060 Laptop, 8 GB VRAM → models ≤ ~8B at Q4 (ADR-0003).
- Python in containers is 3.13; TypeScript pinned to 6.0.x until typescript-eslint supports 7 (ADR-0002).
- GNU make lives in `%LOCALAPPDATA%\Microsoft\WinGet\Packages\ezwinports.make_*\bin` (on PATH in new terminals).
- Demo data checksum (seed 20241101, scale 1.0, dataset v1.0.0): `7ce932275db5…` — identical on Windows and Linux.
- Avoid multi-heredoc Bash commands containing apostrophes in this environment; write files with the editor tools.
- The demo DB image is built locally (`infra/postgres/demo-image`, PostgreSQL 18 + HypoPG); integration
  tests build the same Dockerfile as `nexus-demo-db:test`.
- Playwright signs in as `NEXUS_E2E_EMAIL` (generated into `.env`, created by `make e2e-user`); logins are rate
  limited (5/min), so specs share one signed-in page per project. Git Bash rewrites `/paths` in arguments:
  prefix with `MSYS_NO_PATHCONV=1` when passing routes.
- UI rules enforced by tests: no hex colors outside `src/styles/tokens.css`, no literal JSX text (i18n lint),
  `en` mirrors every `es` key.
