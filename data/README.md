# data

- `retail/schema.sql` — retail demo DDL with `COMMENT ON` for every table and column (RAG source material).
- `retail/generate.py` — deterministic generator (fixed seed), 2024-11-01 → 2026-10-31, ≈500k `detalle_ventas`.
- `glossary.yaml` — versioned business glossary (metric and time definitions).
- `verified_examples/` — question → SQL pairs used as few-shot examples (disjoint from the benchmark golden set).

Populated in Phase 1 (schema, generator, glossary) and Phase 3 (verified examples).
