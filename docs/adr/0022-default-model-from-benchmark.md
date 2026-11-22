# ADR-0022 — Default model chosen from the golden-set benchmark

- Status: Accepted. Supersedes the provisional default of
  [ADR-0003](0003-llm-provider-and-model-selection.md) ("default model pending benchmark") and refines
  its selection rule.
- Date: 2026-11-22

## Context
ADR-0003 deferred the GPU default to data, with a rule fixed in advance: take the configuration with
the highest accuracy, and among those within 2 points of it, the one with the lowest p95 latency.
ADR-0015 fixed the method: a golden set of at least 120 questions, execution accuracy, secondary
metrics, and a CI subset on the CPU model. Phase 6 built the benchmark and ran it.

## What was built
- **Golden set** (`bench/golden/`): 126 Spanish questions (40 easy, 40 medium, 31 hard, 15 ambiguous).
  - The hard tier covers multi-part answers, window functions, period comparisons, shares, the
    new-branch trap, the planted anomalies of ADR-0017, and one follow-up asked after its earlier turn.
  - All gold SQL follows `data/glossary.yaml`. A unit test runs it through the agent's own validator,
    and an integration test runs it read-only on PostgreSQL.
  - Results are frozen in `expected.json` together with the SQL hash and the dataset version.
- **Runner** (`nexus-bench`, `make bench`).
  - Each question runs through the real graph, built with `SourceRuntime.agent_context()`, the same call
    the API uses.
  - Questions are isolated: a long-term memory that stores nothing, and history only for follow-ups.
  - Before running, a leakage check rejects verified few-shot examples that repeat or paraphrase a
    golden question.
  - Results go to `bench/results/*.json`, the app DB (Benchmark page) and `docs/benchmark.md`.
- **Comparison** (`nexus.bench.compare`).
  - Cells become canonical tokens. Gold columns are matched to predicted columns by value; extra
    columns are fine.
  - Rows are compared as multisets, unless the question asks for a ranking.
  - A multi-part question needs a distinct step result for each part; a single result that cross-joins
    two answers does not count.
  - One equivalence is allowed: a `mes`/`anio` period column also matches `2026-03`, `2026-03-01`, a
    month number or Spanish month name (single-year golds only), or a year number.
  - Percent versus fraction, and coarser rounding, are **not** equivalent. Where only the entity
    matters (h016), the gold selects only the entity.

## Results (final run, identical code for every configuration)
Reference GPU: RTX 5060 Laptop, 8 GB. Ollama 0.40.16, temperature 0. Full report:
[docs/benchmark.md](../benchmark.md).

| Configuration | Accuracy | Easy | Medium | Hard | Ambiguous | p50 | p95 | Reference conversation |
|---|---|---|---|---|---|---|---|---|
| `qwen3:8b`, reasoning off | 72.2 % | 90.0 % | 57.5 % | 58.1 % | 93.3 % | 10.8 s | 43.3 s | ✗ follow-up drops the revenue figure |
| **`qwen2.5-coder:7b`** | **71.4 %** | 95.0 % | 65.0 % | 38.7 % | 93.3 % | 8.6 s | 42.8 s | ✓ |
| `gemma4:e4b-it-qat`, reasoning off | 71.4 % | 92.5 % | 65.0 % | 38.7 % | 100 % | 8.7 s | 26.4 s | ✗ never splits the two questions |
| routed: `qwen3:8b` for language nodes + coder for SQL | 69.0 % | 90.0 % | 65.0 % | 35.5 % | 93.3 % | 24.1 s | 58.0 s | ✓ |
| `qwen2.5-coder:3b` (CPU profile) | 57.1 % | 90.0 % | 52.5 % | 22.6 % | 53.3 % | 6.8 s | 32.0 s | ✗ |

## Decision
1. **Selection rule, refined: eligibility comes first.**
   - A configuration can be the default only if it answers the project's reference conversation:
     - h001, the reference question;
     - h031, its follow-up "¿Y en el trimestre anterior?".
   - This conversation has been the acceptance test (`make e2e-agent`) since Phase 2, so the rule now
     states it explicitly. It is enforced in code (`nexus.bench.metrics.REFERENCE_ITEMS`), not by hand.
   - Among eligible configurations, the ADR-0003 rule applies unchanged.
   - The refinement came from the data. On the first run, `gemma4` won the latency tie-break but failed
     the reference question: it cross-joined the top-5 products with the best branch in one query. Its
     `make e2e-agent` run failed for that reason. `qwen3:8b` then answered the follow-up branch without
     its revenue, and failed the same e2e test.
2. **GPU default: `qwen2.5-coder:7b`, unchanged.**
   - It is the most accurate eligible configuration: 71.4 %.
   - The routed configuration is also eligible, but 2.4 points lower (outside the 2-point margin) and
     slower (p95 58 s, because it swaps models on 8 GB).
   - The default did not move, but it is now a measured decision with known weaknesses rather than a
     provisional guess.
3. **Reasoning off** for models that think by default. It is set with `OllamaSettings.think` /
   `NEXUS_LLM_THINK`. Thinking tokens count against the agent's small JSON output budgets and multiply
   latency. Both generalists were measured with reasoning off.
4. **Per-node routing is configuration, not the default.** It is available through
   `NEXUS_LLM_MODEL_<NODE>` and `NEXUS_LLM_EXTRA_MODELS` (ollama-init pulls those models too).
5. **CPU profile stays on `qwen2.5-coder:3b`.**
   - It is the only CPU-sized candidate measured, and it is clearly weaker: 57.1 %, and 53 % on
     ambiguous questions.
   - The README says so; GPU is the supported profile.
6. **CI gate.**
   - `.github/workflows/bench.yml` runs a fixed 15-question subset on `qwen2.5-coder:3b`, which must
     reach `min_accuracy: 0.6`.
   - Calibration: 11/15 = 0.733 on the reference GPU, reproduced exactly in a second run. The 0.6 gate
     allows two questions of drift for CPU inference.
   - The workflow runs when agent, retrieval, SQL, LLM or benchmark code changes, weekly, and on demand.
7. **The PostgreSQL SQL prompt stays pinned by hash** (Phase 5). Any prompt edit needs a new
   `make e2e-agent` run and a new benchmark run.

## How to read these numbers
- **The top three are statistically tied on accuracy.** With 126 questions, the 95 % interval around
  72 % is about ±8 points; they differ by one question.
- **Choose by use case.** The differences are in *what* each configuration gets right.
  - `qwen3:8b` answers far more hard questions (58 % against 39 %).
  - `gemma4` is about 40 % faster at p95, and perfect on ambiguous questions.
  - Neither passes the reference conversation today.
  - A deployment can still choose one with `NEXUS_LLM_MODEL_GPU` (plus `NEXUS_LLM_THINK=false`), as
    long as it accepts that trade-off.
- **Recurring failure modes of the default**, from the run records:
  - `LIMIT 1` added to "¿Cuál es el … promedio por …?" (e006, m004, m040). This over-applies the prompt
    rule for singular superlatives.
  - Only one part of a ratio computed (h019, h023, m016).
  - Filters dropped or invented (m009, m033).
  - Repairs that run out without applying the returns exclusion the glossary requires (m001).
  - These are inputs for prompt and glossary work. Each change must be validated with this benchmark.

## Bugs the benchmark found and that were fixed
- **Tokenizer errors crashed the run.** An unterminated string literal in model SQL raised
  `sqlglot.TokenError`, which the validator did not catch: the whole run failed instead of being
  repaired. The validator now fails closed on any `SqlglotError` and reports `parse_error`. Two cases
  were added to the attack suite.
- **An unusable plan crashed the run.** Truncated JSON from the plan node now falls back to the question
  as the only step, like the `sql_in_plan` guard of ADR-0020.

Both fixes landed before the final run, so every configuration above ran on the same code.

## Consequences
- The Benchmark page shows every configuration and its eligibility, the selection rule, the
  accuracy/latency trade-off, and each question's outcome with its SQL.
- After a model, prompt or glossary change, re-run `make bench`. It updates `docs/benchmark.md`, and the
  selection follows the rule automatically.
