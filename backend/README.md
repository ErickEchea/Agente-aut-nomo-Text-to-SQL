# backend

Python 3.13 package `nexus` (src layout) — FastAPI API + LangGraph agent. Managed with `uv`.
Module map and dependency rules: [`docs/ARCHITECTURE.md` §4](../docs/ARCHITECTURE.md#4-backend-module-map).

```bash
uv sync                      # create .venv with dev dependencies
uv run pytest -m "not integration"   # unit tests
uv run pytest -m integration         # Testcontainers tests (Docker required)
uv run ruff check && uv run ruff format --check
uv run mypy
uv run nexus-seed-demo --help        # demo-data generator/loader (ADR-0017)
```
