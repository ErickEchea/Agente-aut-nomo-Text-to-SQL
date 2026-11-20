# ADR-0008 — Deterministic relative-time resolution with `as_of`

- Status: Accepted
- Date: 2026-11-20

## Context
LLMs are unreliable at calendar arithmetic, and "último trimestre" against a static demo dataset would drift as
the wall clock advances, eventually returning empty results and breaking the benchmark.

## Decision
- `nexus.agent.temporal` is a pure-Python resolver: input = question text, locale, `as_of: date`, week start;
  output = list of `ResolvedRange(expression, start, end_exclusive, grain, assumption_text)`.
- Coverage (es + en): hoy/ayer, esta/la semana pasada, este/el mes pasado, último/este/el trimestre anterior,
  Qn YYYY, primer/segundo semestre, este año/año pasado, YTD/MTD/QTD, últimos N días/semanas/meses, desde/hasta
  fechas explícitas, month names with/without year, "el mismo periodo del año anterior".
- Definitions come from `data/glossary.yaml` (e.g. "último trimestre = trimestre calendario cerrado más
  reciente"), so business rules are data, not code.
- **`as_of`** is a property of each connection. Default: today in the configured timezone. The demo connection
  sets `as_of = 2026-11-01` (data covers 2024-11-01 → 2026-10-31). The resolved range is always shown to the user
  as an assumption ("Último trimestre = 1 jul 2026 – 30 sep 2026 (datos al 1 nov 2026)").
- The LLM receives already-resolved literal bounds and is instructed to use them verbatim; `verify_results`
  checks that generated SQL predicates reference those bounds.

## Consequences
- Fully reproducible benchmark results.
- Expressions the resolver does not recognize are passed through as an explicit "unresolved time expression"
  assumption, and `understand` may ask for clarification instead of guessing.
- Property-based tests (Hypothesis) cover boundary dates (year ends, leap years, quarter edges).
