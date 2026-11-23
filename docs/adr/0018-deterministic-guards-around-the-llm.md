# ADR-0018 — Deterministic guards around the LLM

- Status: Accepted
- Date: 2026-11-20 (Phase 2)

## Context
Phase 2 measured the real default model (`qwen2.5-coder:7b`) on the reference question. It produced
correct SQL for both sub-questions on its first probe, but in later runs it sometimes **omitted the
returns exclusion** from net revenue. That turned Samborondón's Q3 revenue from $299,672.19 into
$309,487.84: plausible, wrong and silent. A 7–8B model follows long instructions probabilistically, so
prompt wording alone cannot guarantee business definitions or safe intent.

## Decision
Wrap the model with deterministic checks. The model proposes; code decides.

1. **Question guard (`nexus.security.guard`)** runs before any model call. It refuses:
   - imperative or command-form requests to modify data, such as "borra", "elimina … clientes" or `DROP TABLE`;
   - well-known injection phrasings ("ignora tus instrucciones", "system prompt", "ahora eres…");
   - privilege requests.

   Analytical questions *about* changes ("¿cuántas ventas se anularon?") are unaffected. The attack suite
   holds both the attacks and these false-positive controls.
2. **Glossary requirements (`data/glossary.yaml` → `requires`)**: a metric can declare the tables and
   string literals that any SQL answering a question about it must contain. For example, «ingresos»
   requires `devoluciones` and `'completada'`. `verify_results` checks the validated AST. If the SQL
   breaks a rule, the node returns a `glossary_violation` with a precise message and the bounded `repair`
   loop rewrites the query. Matching uses the longest phrase, so "ingresos brutos" maps to *ventas
   brutas*, not to *ingresos*.
3. **Date-filter check**: when the question has resolved time ranges, SQL that references none of their
   bounds is sent back to repair (ADR-0008).
4. **Catalog hints for repairs (after Phase 7, `nexus.sql.columns`)**.
   - Problem: engine errors do not say where the query looked. PostgreSQL reports
     `column "region_id" does not exist` and `operator does not exist: text = integer` without naming
     the table or the columns.
   - Effect: with only that, the model rewrote the same SQL until the repair budget ran out.
   - Decision: the failed SQL is resolved scope by scope against the catalog and the query's own CTEs
     and subqueries. The repair prompt's error block then also says:
     - which source lacks the column, and what that source really returns;
     - when a CTE hides a real table of the same name;
     - which tables do have the column;
     - for a comparison of incompatible types, both columns, their types and their origin.
   - Scope: only columns and types that the engine's message names are reported, so a resolution gap
     cannot mislead.
5. **No fixed point in the repair loop**. Decoding is greedy (temperature 0), so the seed changes
   nothing: once a repair returns the SQL it was given, the same prompt returns it again.
   - A repair can return the SQL it was asked to fix, or any SQL this step already tried. The 7B
     model was seen alternating between two failing queries.
   - Such a repair is asked once more, saying so, at temperature 0.7 with a fixed seed. It stays
     reproducible.
   - Comparison ignores whitespace, case and a trailing `;`, against both the raw and the validator's
     rendering.

## Consequences
- The reference question passed 3/3 consecutive live runs. In each run the glossary check caught the
  missing exclusion on the second step, and one repair fixed it, at a cost of about 5 s.
- Business rules live in data (the glossary), where analysts can extend them without touching code.
- Checks are syntactic, not semantic. A query that references `devoluciones` in a useless way would still
  pass. The Phase 6 benchmark measures the residual error rate.
- Hints make repairs informed, not guaranteed. «¿Cuántos clientes nuevos se registraron por región este
  año?» still fails with the 7B model:
  - customers have no `region_id`; their region is their province's, through `sucursales`;
  - the model receives accurate hints but keeps joining `cliente_id` to `region_id`.

  Spelling that path out in the «región» glossary entry made it worse:
  - the model then joined customers to branches by province without `DISTINCT`;
  - each customer was counted once per branch in their province;
  - the answer came back plausible, inflated and silent.

  A wrong answer is worse than an honest failure, so the entry was reverted. The 3B CPU model
  also produced runaway JSON on «Ingresos por región en 2025» with that entry.

  The question is kept as an `xfail` end-to-end test. Asked by province, the same question is answered
  correctly.
