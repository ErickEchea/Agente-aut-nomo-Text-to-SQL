# ADR-0004 — Agent orchestration with LangGraph

- Status: Accepted
- Date: 2026-11-20

## Context
The pipeline has 12 steps with conditional branches (clarify, refuse), a bounded repair loop, a per-step loop for
compound questions, and an explanation retry loop. Each step must emit lifecycle events and be testable alone.

## Decision
- One `StateGraph[AgentState]` (see ARCHITECTURE §5). Nodes are plain `async def node(state, deps) -> dict`
  functions in `nexus/agent/nodes/`, so they can be unit-tested without the graph.
- Dependencies (LLM provider, retriever, executor, clock, event sink) are injected through LangGraph's runtime
  context, not globals.
- Routing functions are pure and exhaustively unit-tested (every edge).
- Loop budgets live in state (`attempts`, `explain_retries`) and are enforced by routing functions, plus
  LangGraph's `recursion_limit` as a backstop.
- **Compound questions**: `plan` emits `steps[]` with strategy `single_cte` (one query using CTEs when steps share
  filters/grain) or `multi_query` (independent queries, e.g. the reference question: top-5 products by units vs.
  top branch by revenue have different grains). Steps run sequentially so the timeline order is stable.
- **Events**: a node wrapper (decorator) emits `node.started/completed/failed` with duration and token usage, and
  writes a span to the log. Nodes never emit events themselves.
- **Checkpointing**: conversation memory lives in our own app-DB tables (`conversations`, `runs`, `feedback`,
  `user_preferences`, `verified_examples`), not in LangGraph checkpointers, because we need queryable history and
  feedback, not graph resumption. `understand` loads the last N turns of the conversation to resolve follow-ups
  ("¿y en el trimestre anterior?") into a standalone question.

## Alternatives considered
- Hand-written async state machine: less code but we would re-implement branching, typed state reducers and
  visualization (`graph.get_graph().draw_mermaid()` is used to keep the diagram in sync).
- LangChain AgentExecutor / ReAct tool loop: non-deterministic control flow is the wrong shape for a pipeline
  that must be auditable and benchmarkable.

## Consequences
- The graph is deterministic given the LLM outputs, so the benchmark can attribute failures to a node.
- A test asserts the compiled graph's Mermaid export equals the committed diagram fragment.
