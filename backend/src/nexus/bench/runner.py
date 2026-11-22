"""Run the golden set through the real agent graph for one model configuration (ADR-0015).

Each question runs exactly as in the API (same graph, source runtime, validator, read-only executor
and retriever) with three differences that keep the measurement clean:
- no conversation history, so questions are independent;
- the long-term memory sink stores nothing, so one question cannot teach the next;
- audit records and node events are collected into the result instead of the app database.
"""

from __future__ import annotations

import time
import uuid
from collections.abc import Awaitable, Callable, Sequence
from dataclasses import dataclass, field
from pathlib import Path
from typing import Literal

import structlog
import yaml
from langgraph.graph.state import CompiledStateGraph
from pydantic import BaseModel, ConfigDict, Field

from nexus.agent.graph import run_agent
from nexus.agent.state import (
    AgentContext,
    AgentState,
    AuditSink,
    EventSink,
    HistoryTurn,
    MemorySink,
    NodeModels,
    RunStatus,
)
from nexus.bench.compare import PredictedResult, score_answer
from nexus.bench.golden import ExpectedResults, GoldenItem
from nexus.llm import LLMError

logger = structlog.get_logger("nexus.bench")
WARMUP_QUESTION = "¿Cuántas sucursales tiene la cadena?"


class BenchConfig(BaseModel):
    """A model configuration: default model, optional per-node routing, reasoning toggle."""

    model_config = ConfigDict(frozen=True, extra="forbid")

    name: str = Field(pattern=r"^[a-z0-9][a-z0-9._-]{1,60}$")
    model: str
    nodes: dict[
        Literal["understand", "plan", "generate", "repair", "visualize", "explain"], str
    ] = Field(default_factory=dict)
    think: bool | None = None
    description: str = ""

    def routing(self) -> NodeModels:
        get = self.nodes.get
        return NodeModels(
            understand=get("understand"),
            plan=get("plan"),
            generate=get("generate"),
            repair=get("repair"),
            visualize=get("visualize"),
            explain=get("explain"),
        )

    @property
    def models(self) -> tuple[str, ...]:
        return tuple(dict.fromkeys((self.model, *self.nodes.values())))

    @classmethod
    def single(cls, model: str, think: bool | None = None) -> BenchConfig:
        name = model.replace(":", "-").replace("/", "-").lower()
        return cls(name=name, model=model, think=think)


def load_configs(path: Path) -> dict[str, BenchConfig]:
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    configs = [BenchConfig.model_validate(item) for item in raw.get("configs", [])]
    return {config.name: config for config in configs}


@dataclass(slots=True)
class _Events:
    """Collects per-node durations and token usage from the graph's instrumentation events."""

    nodes: list[dict[str, object]] = field(default_factory=list)

    async def emit(self, event: str, data: dict[str, object]) -> None:
        if event == "node.completed":
            tokens = data.get("tokens")
            usage = tokens if isinstance(tokens, dict) else {}
            self.nodes.append(
                {
                    "node": data.get("node"),
                    "step": data.get("step"),
                    "duration_ms": data.get("duration_ms"),
                    "prompt_tokens": usage.get("prompt", 0),
                    "completion_tokens": usage.get("completion", 0),
                }
            )


@dataclass(slots=True)
class _Audit:
    """Keeps every SQL attempt's outcome with the result instead of the app's audit log."""

    attempts: list[dict[str, object]] = field(default_factory=list)

    async def record(
        self,
        *,
        question: str,
        sql: str,
        outcome: str,
        row_count: int | None,
        duration_ms: float | None,
        error_code: str | None,
    ) -> None:
        self.attempts.append({"outcome": outcome, "error_code": error_code, "row_count": row_count})


class IsolatedMemory:
    """Long-term memory that stores nothing: benchmark questions must not influence each other."""

    async def remember(self, *, question: str, standalone: str, status: str) -> None:
        return None


class ItemOutcome(BaseModel):
    item_id: str
    difficulty: str
    question: str
    status: str
    correct: bool
    reason: str
    latency_ms: float
    prompt_tokens: int = 0
    completion_tokens: int = 0
    llm_calls: int = 0
    sql_attempts: int = 0
    repairs: int = 0
    first_attempt_ok: bool = False
    explanation_fallback: bool | None = None
    recall_at_5: float | None = None
    context_complete: bool | None = None
    sql: list[str] = Field(default_factory=list)
    error: str | None = None
    nodes: list[dict[str, object]] = Field(default_factory=list)


ContextFactory = Callable[[EventSink, AuditSink, MemorySink], Awaitable[AgentContext]]


def _retrieval(state: AgentState, item: GoldenItem) -> tuple[float | None, bool | None]:
    context = state.get("schema_context")
    gold = item.gold_tables if item.answers else frozenset()
    if context is None or not gold:
        return None, None
    top5 = {ranked.name.lower() for ranked in context.ranked[:5]}
    chosen = {table.lower() for table in context.tables}
    return round(len(gold & top5) / len(gold), 4), gold <= chosen


def _score(state: AgentState, item: GoldenItem, expected: ExpectedResults) -> tuple[bool, str]:
    status = state.get("status")
    if not item.answers:
        executed = bool(state.get("results"))
        if status is RunStatus.CLARIFICATION and not executed:
            return True, "clarified"
        return False, "answered_ambiguous" if executed else f"status_{status}"
    if status is not RunStatus.ANSWERED:
        return False, f"status_{status}"
    frozen = expected.items[item.id]
    predicted = [PredictedResult(r.columns, list(r.rows)) for r in state.get("results", [])]
    match = score_answer(frozen.results, predicted, order_matters=item.order_matters)
    return match.ok, match.reason


def outcome_from_state(
    item: GoldenItem,
    state: AgentState,
    expected: ExpectedResults,
    *,
    latency_ms: float,
    events: _Events,
    audit: _Audit,
) -> ItemOutcome:
    correct, reason = _score(state, item, expected)
    attempts = state.get("attempts", [])
    first = [a for a in attempts if a.attempt == 1]
    recall, complete = _retrieval(state, item)
    explanation = state.get("explanation")
    usage = state.get("usage", [])
    return ItemOutcome(
        item_id=item.id,
        difficulty=item.difficulty.value,
        question=item.question,
        status=str(state.get("status", "failed")),
        correct=correct,
        reason=reason,
        latency_ms=round(latency_ms, 1),
        prompt_tokens=sum(u.prompt_tokens for u in usage),
        completion_tokens=sum(u.completion_tokens for u in usage),
        llm_calls=len(usage),
        sql_attempts=len(attempts),
        repairs=sum(1 for a in attempts if a.attempt > 1),
        first_attempt_ok=bool(first) and all(a.outcome == "ok" for a in first),
        explanation_fallback=explanation.fallback if explanation is not None else None,
        recall_at_5=recall,
        context_complete=complete,
        sql=[result.sql for result in state.get("results", [])],
        error=None if state.get("last_error") is None else state["last_error"].code,  # type: ignore[union-attr]
        nodes=events.nodes,
    )


def history_turn(state: AgentState) -> HistoryTurn:
    """The short-term memory the API keeps for an answered turn (nexus.memory.store)."""
    time_resolution = state.get("time")
    return HistoryTurn(
        question=state["question"],
        standalone=state.get("standalone_question") or state["question"],
        ranges=time_resolution.ranges if time_resolution is not None else (),
        answer=state.get("answer", "")[:300],
    )


async def _history(
    graph: CompiledStateGraph[AgentState, AgentContext, AgentState, AgentState],
    make_context: ContextFactory,
    questions: Sequence[str],
) -> list[HistoryTurn]:
    """Ask the earlier turns of a conversation (not timed, not scored)."""
    turns: list[HistoryTurn] = []
    for question in questions:
        ctx = await make_context(_Events(), _Audit(), IsolatedMemory())
        state = await run_agent(
            graph, ctx, run_id=f"bench-{uuid.uuid4()}", question=question, history=list(turns)
        )
        turns.append(history_turn(state))
    return turns


async def run_item(
    graph: CompiledStateGraph[AgentState, AgentContext, AgentState, AgentState],
    make_context: ContextFactory,
    item: GoldenItem,
    expected: ExpectedResults,
) -> ItemOutcome:
    events, audit = _Events(), _Audit()
    started = time.perf_counter()
    try:
        history = await _history(graph, make_context, item.history)
        ctx = await make_context(events, audit, IsolatedMemory())
        started = time.perf_counter()
        state = await run_agent(
            graph, ctx, run_id=f"bench-{uuid.uuid4()}", question=item.question, history=history
        )
    except (LLMError, TimeoutError) as exc:
        elapsed = (time.perf_counter() - started) * 1000
        logger.warning("bench.item_error", item=item.id, error=str(exc))
        return ItemOutcome(
            item_id=item.id,
            difficulty=item.difficulty.value,
            question=item.question,
            status="error",
            correct=False,
            reason="llm_error",
            latency_ms=round(elapsed, 1),
            error=str(exc)[:300],
            nodes=events.nodes,
        )
    elapsed = (time.perf_counter() - started) * 1000
    return outcome_from_state(item, state, expected, latency_ms=elapsed, events=events, audit=audit)


async def run_items(
    graph: CompiledStateGraph[AgentState, AgentContext, AgentState, AgentState],
    make_context: ContextFactory,
    items: Sequence[GoldenItem],
    expected: ExpectedResults,
    *,
    warmup: bool = True,
    on_item: Callable[[ItemOutcome], None] | None = None,
) -> list[ItemOutcome]:
    """Run every item in order after one warm-up question that loads the models (not timed)."""
    if warmup:
        events, audit = _Events(), _Audit()
        ctx = await make_context(events, audit, IsolatedMemory())
        try:
            await run_agent(graph, ctx, run_id="bench-warmup", question=WARMUP_QUESTION)
        except (LLMError, TimeoutError) as exc:
            logger.warning("bench.warmup_failed", error=str(exc))
    outcomes = []
    for item in items:
        outcome = await run_item(graph, make_context, item, expected)
        outcomes.append(outcome)
        if on_item is not None:
            on_item(outcome)
    return outcomes
