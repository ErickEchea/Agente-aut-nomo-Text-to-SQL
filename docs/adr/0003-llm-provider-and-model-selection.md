# ADR-0003 — LLM provider abstraction and model selection

- Status: Accepted. The default model was selected by the Phase 6 benchmark: `qwen2.5-coder:7b`, see
  [ADR-0022](0022-default-model-from-benchmark.md), which also adds an eligibility gate to the rule in §4.
- Date: 2026-11-20

## Context
LLMs run locally through Ollama; no paid APIs. The reference machine has an **NVIDIA RTX 5060 Laptop, 8 GB VRAM**.
That rules out the newest large families on GPU (qwen3.6/3.8 27B+, qwen3-coder 30B, gemma4 26B/31B all need
16–23 GB) unless they spill to CPU, which makes interactive latency unacceptable. The embedding model must share
the same VRAM. The default model must be chosen from benchmark data, not intuition.

## Decision
1. **`LLMProvider` protocol** (backend `nexus.llm`):
   ```python
   class LLMProvider(Protocol):
       async def complete(self, messages: Sequence[Message], *, schema: type[T] | None,
                          options: GenerationOptions) -> Completion[T]: ...
       async def stream(self, messages: Sequence[Message], options: GenerationOptions) -> AsyncIterator[str]: ...
       async def embed(self, texts: Sequence[str]) -> list[list[float]]: ...
       async def health(self) -> ProviderHealth: ...
   ```
   `OllamaProvider` uses the official `ollama` async client and Ollama's JSON-schema structured output
   (`format=<schema>`), then validates with Pydantic. Token usage comes from Ollama's `prompt_eval_count` /
   `eval_count`. Any other provider (vLLM, llama.cpp server, a paid API) is a new class; nodes never import Ollama.
2. **Candidates** (verified in the Ollama library on 2026-11-20; sizes are Q4 downloads):

   | Role | Model | Size | Why |
   |---|---|---|---|
   | Code/SQL specialist | `qwen2.5-coder:7b` | 4.7 GB | Strongest code model that fits 8 GB with KV-cache headroom. |
   | Generalist reasoning | `qwen3:8b` | 5.2 GB | Hybrid thinking mode; good Spanish; already cached on the dev machine. |
   | Generalist (newest family) | `gemma4:e4b-it-qat` | 6.1 GB | Newest small generalist; QAT keeps quality at Q4. Tightest fit. |
   | CPU mode | `qwen2.5-coder:3b` (alt. `qwen3:4b`) | 1.9 / 2.5 GB | Usable on CPU-only machines and in CI. |

   `granite4.2:8b` (5.3 GB) is a reserve candidate if one of the above fails structured output reliably.
3. **Per-node model routing** is configuration, not code: e.g. `understand`/`plan`/`explain` may use the
   generalist while `generate_sql`/`repair` use the specialist. The benchmark evaluates (a) single-model and
   (b) routed configurations. With 8 GB, routing implies model swaps; Ollama `keep_alive` and
   `OLLAMA_MAX_LOADED_MODELS` are tuned and the swap cost shows up in the latency metrics.
4. **Selection rule** (Phase 6): maximize execution accuracy on the golden set; among configurations within
   2 percentage points of the best, pick the lowest p95 latency. Result recorded in a superseding ADR and
   `docs/benchmark.md`.
5. **Profiles**: `GPU` (default when `nvidia-smi` is present) and `CPU` (smaller model, longer timeouts).

## Alternatives considered
- `sqlcoder:15b`: SQL-specific but 9 GB at Q4, old base model, weak instruction following in Spanish.
- MoE models (`qwen3.6:35b-a3b`, `qwen3-coder:30b-a3b`): fast per token but 19–23 GB of weights; on 8 GB they
  offload to CPU. Documented as an option for bigger GPUs, not a default.
- `langchain-ollama` chat model: adds an abstraction we don't control; structured output is simpler via the
  native client.

## Consequences
- Accuracy on hard questions is bounded by 7–8B models; RAG quality, verified few-shot examples, deterministic
  time resolution and the repair loop carry much of the weight, and the benchmark will show it honestly.
- `make up` downloads ~6–11 GB of models on first run (`ollama-init` service).
