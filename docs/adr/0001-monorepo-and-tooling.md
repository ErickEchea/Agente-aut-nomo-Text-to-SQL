# ADR-0001 — Monorepo layout and toolchain

- Status: Accepted
- Date: 2026-11-20

## Context
NEXUS AI has a Python backend, a TypeScript frontend, a demo-data generator, a benchmark and infrastructure.
They share contracts (SSE events, API schemas, chart specs) and must be versioned together. Development happens
on Windows 11; everything runs in Linux containers and in GitHub Actions.

## Decision
Single repository:

```
backend/     Python package `nexus` (src layout), tests, Dockerfile, Alembic
frontend/    React app, Vitest + Playwright tests, Dockerfile (nginx)
data/        retail schema DDL, seeded generator, glossary YAML, verified examples
bench/       golden set (YAML), runner, report renderer
infra/       Postgres init scripts (roles, extensions), nginx config
docs/        ARCHITECTURE, DESIGN, ADRs, benchmark report
.github/     CI workflows
```

- **Python**: `uv` for environments and locking (`uv.lock` committed). `ruff` (lint + format), `mypy --strict`, `pytest`.
- **Frontend**: `npm` with `package-lock.json` (pnpm is not installed on the dev machine and adds no capability we need).
- **Task runner**: `make` is the single entry point (`make up`, `make test`, `make bench`, …). On Windows it is
  installed with `winget install ezwinports.make` and run from Git Bash; recipes only use POSIX sh.
- **Hooks**: `pre-commit` runs ruff (lint + format), mypy, eslint, `tsc --noEmit` and hygiene hooks
  (trailing whitespace, EOF, large files, private keys).
- **Commits**: Conventional Commits, small and scoped (`feat(agent): …`, `test(security): …`).
- **Line endings**: `.gitattributes` forces LF because `core.autocrlf=true` on the dev machine would otherwise
  break shell scripts and SQL files mounted into containers.

## Alternatives considered
- Polyrepo: rejected — contract changes would need coordinated releases.
- Nx/Turborepo: unnecessary for one TS package; adds a Node toolchain to the Python side.
- Poetry: slower and its lockfile is less portable than `uv.lock`.

## Consequences
- One CI pipeline with path filters per area.
- Windows contributors need Git Bash + make; documented in the README.
