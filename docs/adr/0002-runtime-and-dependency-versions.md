# ADR-0002 — Runtime and dependency versions

- Status: Accepted
- Date: 2026-11-20

## Context
The brief requires real, current, pinned versions. Versions below were verified on 2026-11-20 against PyPI,
the npm registry, Docker Hub and the GitHub releases API. Exact versions are pinned in lockfiles; this ADR records
the baseline and the reasoning where we deliberately do **not** take the latest.

## Decision

**Runtimes**
| Component | Version | Note |
|---|---|---|
| Python (containers) | 3.13 | numpy 2.5 requires ≥3.12; 3.13 has full wheel coverage for asyncpg/psycopg/cryptography. |
| Node | 24 LTS | Matches the dev machine. |
| PostgreSQL | 18 (`pgvector/pgvector:0.8.7-pg18-trixie`, `postgres:18`) | PG 19 is available but very recent; PG 18 has broader tooling/Testcontainers support. |
| Ollama | 0.40.16 (`ollama/ollama:0.40.16`) | Pinned; the host install (0.24) is not used by the stack. |
| MySQL (multi-DB tests) | 8.4 LTS | |

**Backend baseline**: fastapi 0.165, pydantic 2.14, pydantic-settings 2.16, sqlalchemy 2.1, alembic 1.20,
asyncpg 0.32, psycopg 3.3, aiomysql 0.3, aiosqlite 0.22, pgvector 0.5, langgraph 1.2, langchain-core 1.8,
ollama (python client) 0.6, sqlglot 30.33, structlog 26.1, pyjwt 2.15, argon2-cffi 25.1, cryptography 50.0,
sse-starlette 3.7, httpx 0.28, numpy 2.5, pyyaml 6.0. Dev: pytest 9.2, pytest-asyncio 1.5, testcontainers 4.15,
hypothesis 6.170, ruff 0.17, mypy 2.4, pre-commit 4.7. (The FK join-path search is ~40 lines of our own BFS code;
`networkx` is not needed.)

**Frontend baseline**: react 19.3, vite 8.3, **typescript 6.0.3**, tailwindcss 4.3, shadcn CLI 4.23,
motion 14.14, @tanstack/react-query 5.108, @tanstack/react-table 9.3, @tanstack/react-virtual 3.14, echarts 6.1,
react-router 8.5, i18next 27 + react-i18next 18, shiki 4.6, zod 4.6, cmdk 1.1, lucide-react 1.77, diff 9.0.
Build: @vitejs/plugin-react 6.3 (peer `vite ^8`). Dev: vitest 5.1, @playwright/test 1.65,
@axe-core/playwright 4.14, eslint 10.15, typescript-eslint 8.73.

## Deliberate deviations from "latest"
- **TypeScript 6.0.3, not 7.0.2**: typescript-eslint 8.73 declares `typescript >=4.8.4 <6.1.0`. Type-aware lint
  rules are part of the quality bar, so we take the newest TS inside that range. Revisit when typescript-eslint
  supports TS 7 (tracked in PROGRESS.md).
- **No LangChain chains/agents**: only `langchain-core` types required by LangGraph. LLM calls go through our own
  `LLMProvider` (ADR-0003), avoiding the churn of `langchain-ollama`.
- **No slowapi**: last release 0.1.10 is old; see ADR-0011.
- **`motion` package** is Framer Motion's current distribution name; it is the same library.

## Consequences
- Version bumps go through Renovate-style manual PRs; CI must be green.
- The README lists the verified versions with the date they were checked.
