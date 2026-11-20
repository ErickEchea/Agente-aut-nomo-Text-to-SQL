# PROGRESS

Phase plan and exit criteria: [`docs/ROADMAP.md`](docs/ROADMAP.md).

## Status

| Phase | State |
|---|---|
| 0 — Plan, ADRs, structure | ✅ Done — awaiting approval to start Phase 1 |
| 1 — Infra, demo DB, read-only role | ⏳ Not started |
| 2 — Agent core + security | ⏳ |
| 3 — RAG + memory | ⏳ |
| 4 — Frontend + design system | ⏳ |
| 5 — Explainability, optimization, multi-DB | ⏳ |
| 6 — Benchmark + default model | ⏳ |
| 7 — Hardening + docs | ⏳ |

## Phase 0 — 2026-11-20

### Done
- Environment survey: Windows 11, Docker 29.9 / Compose v5.7, Python 3.11 + 3.14 (host), uv 0.11, Node 24,
  npm 11, ffmpeg 8.1, NVIDIA RTX 5060 Laptop (8 GB VRAM, driver 621.24), host Ollama 0.24 with `qwen3:8b` cached.
- Verified current versions of all planned dependencies, Docker images and Ollama models (ADR-0002, ADR-0003).
- `CLAUDE.md`, `docs/ARCHITECTURE.md`, `docs/ROADMAP.md`, ADR-0001…0016, `.gitattributes`, `.gitignore`,
  `.editorconfig`, area READMEs describing the monorepo layout.

### Known issues / risks
- **8 GB VRAM** limits candidates to ≤ ~8B models; the newest large families (qwen3.6/3.8, gemma4 26B+,
  qwen3-coder 30B) are documented but not defaults. Hard-question accuracy will reflect that.
- **TypeScript 7** cannot be used yet: typescript-eslint 8.73 supports `<6.1`. Pinned to 6.0.3.
- **`make` and `gh` are not installed** on the dev machine. `make` will be installed via winget in Phase 1.
  Without `gh` + a GitHub remote, CI can be written and run locally (lint/test steps) but "CI green on GitHub"
  cannot be verified.
- Docker Desktop was not running during the survey; GPU passthrough (WSL2 + NVIDIA) is verified in Phase 1.
- Host ports 5432 (local Postgres) and 11434 (host Ollama) are occupied; the stack uses alternative host ports.
- Single-replica assumptions: in-process rate limiter (ADR-0011) and SSE fan-out queue (ADR-0009).
