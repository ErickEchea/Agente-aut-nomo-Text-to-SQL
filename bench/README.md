# bench

The golden-set benchmark that measures NEXUS AI end to end and chooses the default model from data.
Methodology: [ADR-0015](../docs/adr/0015-benchmark-methodology.md). Decision and calibration:
[ADR-0022](../docs/adr/0022-default-model-from-benchmark.md). Latest report:
[docs/benchmark.md](../docs/benchmark.md).

## Layout

| Path | What |
|---|---|
| `golden/easy.yaml` … `golden/ambiguous.yaml` | 126 Spanish questions, each tagged `easy`, `medium`, `hard` or `ambiguous`. Every answerable question has gold SQL that follows `data/glossary.yaml`. Relative dates use the demo's reference date, 2026-11-01. |
| `golden/expected.json` | The frozen result of every gold query, stored as canonical cell tokens. Each entry records the SHA-256 of its gold SQL and the dataset version, so a unit test fails if a query changes without re-freezing. |
| `configs.yaml` | The model configurations to compare, and the CI subset with its calibrated accuracy gate. |
| `results/*.json` | One record per run: configuration, summary metrics and every question's outcome. These files feed `docs/benchmark.md`. |
| `retrieval/questions.yaml` | The schema-retrieval evaluation set (Phase 3, `make eval-retrieval`). |

## Commands (stack up)

```bash
make bench-freeze                       # re-run the gold SQL (validated, read-only) → golden/expected.json
make bench                              # every configuration in configs.yaml → results/ + docs/benchmark.md
make bench CONFIGS="qwen3-8b"           # one named configuration
make bench MODELS="llama3.2:3b" CONFIGS=  # any pulled Ollama model, reasoning off
make bench SUBSET=e001,m001,h001        # a few questions
make bench-ci                           # CI subset on the CPU model plus the accuracy gate
make bench-report                       # re-render docs/benchmark.md from results/
```

The runner works inside the backend image (`docker compose run`, with `bench/` and `docs/` mounted). It
uses the same agent graph, read-only role, validator, retriever and Ollama as the API. Each question
runs on its own: no conversation history, and nothing is written to long-term memory. Before the run
starts, the runner checks that no verified few-shot example repeats or paraphrases a golden question.

## How a question is scored

- **Answerable questions** are scored by execution accuracy. The agent's result must contain every gold
  column with the same values: numbers rounded to 2 decimals, dates as ISO, and a month or year written
  in any common form. Rows are compared as a set, unless the question asks for a ranking. Extra columns
  are fine. A multi-part question needs one matching step per part.
- **Ambiguous questions** count as correct only when the agent asks for clarification and runs no SQL.
- **Follow-ups** list the earlier turns in `history`. The runner asks those turns first, in the same
  conversation, and scores only the last one.
- **Eligibility.** A configuration can become the default only if it answers the reference
  conversation: h001 (the reference question) and h031 (its follow-up). That is the
  `make e2e-agent` acceptance test (ADR-0022).

## Adding a question

1. Add it to the right `golden/<difficulty>.yaml` with the next free id and gold SQL that follows the
   glossary.
2. Run `make bench-freeze`. Check the printed row count: an empty result, or one with more than 1 000
   rows, is rejected.
3. Run `cd backend && uv run pytest tests/unit/bench` to check balance, the validator and that the
   frozen answers are up to date.
