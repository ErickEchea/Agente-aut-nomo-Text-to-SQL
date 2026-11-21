# ADR-0021: Deterministic SQL annotation and the plan-based optimizer

- Status: Accepted
- Date: 2026-11-21

## Context
Phase 5 adds two features to every answered step:
- an explanation of the generated SQL, clause by clause, where each clause is linked to its span in the
  query;
- an optimization analysis that shows the plan, flags expensive reads and proposes indexes, with the
  cost before and after where the engine can estimate it.

Both explain SQL that is already validated. Neither can be allowed to invent anything, and neither can
change the user's database.

## Decision

### Annotation: `nexus.sql.annotate`
- **No LLM.** The query is split with the dialect's own sqlglot tokenizer at the clause keywords of the
  main query and of each CTE body. Subqueries inside predicates stay within their clause.
- Clauses are re-flowed one per line for display. Each clause carries exact `[start, end)` offsets into
  the displayed SQL, and the frontend maps Shiki token offsets onto them, so focusing a clause card
  highlights its span.
- Descriptions are built from the AST and the catalog. They cover:
  - the meaning of each output column, from the column comments;
  - table comments;
  - predicates (`=`, ranges, `IN`, `BETWEEN`, `LIKE`, `IS [NOT] NULL`, `[NOT] EXISTS`);
  - grouping and ordering;
  - the `LIMIT` that NEXUS added itself.
- A glossary rule (ADR-0018) is listed under a clause only when that clause satisfies the rule's
  `requires`. The explanation therefore cannot claim that a rule was applied when the SQL does not
  apply it.
- Spanish and English texts come from the backend: `GET /api/runs/{id}/steps/{n}/annotation?locale=`.
  These are domain sentences, not UI chrome, so they live next to the AST logic.

### Optimizer: `nexus.sql.optimizer`
1. Ask the engine for its plan; the query itself is never executed:
   - PostgreSQL: `EXPLAIN (FORMAT JSON)`;
   - MySQL: `EXPLAIN FORMAT=JSON`;
   - SQLite: `EXPLAIN QUERY PLAN`.
2. Normalise the plan into steps and flag full scans of large tables. A table is large above 5 000
   rows, using the engine's row estimate.
3. From the AST, collect the columns each scanned table is filtered or joined on that no existing index
   starts with. Each becomes a candidate (at most 4).
4. **PostgreSQL + HypoPG 1.4.5.** Re-plan the query with each candidate created as a *hypothetical*
   index (`hypopg_create_index`). Keep a candidate only if the planner uses it and the cost drops by at
   least 10 %. Each kept suggestion carries `cost_before` and `cost_after`.
5. **MySQL and SQLite.** Report the scan and the suggested index without a before/after cost, and say so
   in the UI:
   - MySQL reports the total `query_cost`;
   - SQLite has no cost model.
6. Suggestions are DDL text built from catalog identifiers, with a copy button. **NEXUS never creates
   an index.**

### Safety around HypoPG
- HypoPG lives in its own schema, `hypopg`. `nexus_reader` gets only `USAGE`, granted by the
  one-shot `demo-extensions` service.
- The validator denies every `hypopg_*` function. Generated SQL cannot call them; only the optimizer
  can, through `ReadOnlyExecutor.explain_with_hypothetical_index`.
- Hypothetical indexes belong to the backend session and **survive `ROLLBACK`**. The executor
  therefore invalidates that pooled connection after use, so no hypothetical index can leak into
  another query's plan.
- The demo image is `infra/postgres/demo-image`: `postgres:18.7-trixie` plus the PGDG package
  `postgresql-18-hypopg=1.4.5-1.pgdg13+2`. Integration tests build the same Dockerfile.

## Alternatives considered
- **LLM-written clause explanations.** Rejected: they are slower, can be wrong, and are hard to
  ground. The executive summary already uses the LLM under a number-grounding check (ADR-0014). The
  SQL walkthrough needs to be exact.
- **`CREATE INDEX` inside a rolled-back transaction to measure the gain.** Rejected: it needs write
  privileges, takes locks and builds a real index on large tables. HypoPG gives the planner's estimate
  at no cost.
- **pg_qualstats / index advisors.** These need workload history and `shared_preload_libraries`.
  They are overkill for analysing a single query.

## Consequences
- The planted missing index `detalle_ventas(producto_id)` is found on the full-scale demo. For
  "¿Cuántas unidades de Agua mineral 1.5 L se vendieron en total?" the estimated cost drops from
  7 521.5 to 3 135.2 (−58 %). The integration test at test scale shows 252.8 → 139.0.
- On MySQL and SQLite the user gets correct scan findings and DDL, but no measured gain.
- External PostgreSQL sources without HypoPG fall back to suggestions without costs. The optimizer
  detects the missing extension and stops trying.
