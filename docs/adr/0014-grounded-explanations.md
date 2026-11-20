# ADR-0014 — Grounded executive summaries

- Status: Accepted
- Date: 2026-11-20

## Context
Small models hallucinate figures. An executive summary with a wrong number is worse than no summary.

## Decision
- `explain` receives only: the question, assumptions, column metadata and the result rows (or, for large
  results, the top rows plus deterministic aggregates computed in Python — which are then also part of the
  "allowed numbers" set).
- Output is structured: `{headline, bullets[], caveats[]}`.
- **Grounding check**: extract every numeric token from the text (handling es/en formats: `1.234,56`, `1,234.56`,
  `12,5 %`, `$1.2 M`, `3 mil`), normalize, and require each to match a value in the allowed set within the
  displayed precision (rounding tolerance). Ordinals/counts that equal the row count, years and quarter numbers
  from resolved ranges are allowed explicitly.
- On failure: regenerate with the offending numbers listed (max 2 retries). If still ungrounded, fall back to a
  deterministic template summary built from the data — the UI marks it as such.

## Consequences
- Summaries can be less fluent but are never numerically wrong; the benchmark tracks the grounding failure rate.
