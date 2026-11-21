# data

- `retail/schema.sql` — retail demo DDL with `COMMENT ON` for every table and column (RAG source material).
- `retail/constraints.sql` — foreign keys and indexes applied after `COPY` (no index on
  `detalle_ventas(producto_id)` on purpose — ADR-0017).
- The deterministic generator lives in the backend package (`nexus.demo`, CLI `nexus-seed-demo`);
  2024-11-01 → 2026-10-31, ≈500k `detalle_ventas`, fixed seed.
- `glossary.yaml` — versioned business glossary (metric and time definitions).
- `sqlite/` — SQLite files that can be registered as data sources (mounted read-only at `/data/sqlite`);
  `make sqlite-demo` exports `retail_mini.sqlite` there. Generated files are git-ignored.

Verified few-shot examples are not files: they are created from answers rated correct in the app and
stored in the app DB (ADR-0019).
