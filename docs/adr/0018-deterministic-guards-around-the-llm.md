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

## Consequences
- The reference question passed 3/3 consecutive live runs. In each run the glossary check caught the
  missing exclusion on the second step, and one repair fixed it, at a cost of about 5 s.
- Business rules live in data (the glossary), where analysts can extend them without touching code.
- Checks are syntactic, not semantic. A query that references `devoluciones` in a useless way would still
  pass. The Phase 6 benchmark measures the residual error rate.
