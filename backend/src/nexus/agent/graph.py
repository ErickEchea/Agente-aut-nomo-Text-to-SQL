"""The LangGraph state graph (ARCHITECTURE §5): instrumented nodes, pure routing functions."""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable
from typing import Literal

import structlog
from langgraph.graph import END, START, StateGraph
from langgraph.graph.state import CompiledStateGraph
from langgraph.runtime import Runtime

from nexus.agent import nodes
from nexus.agent.state import AgentContext, AgentState, HistoryTurn, Intent
from nexus.llm import TokenUsage

logger = structlog.get_logger("nexus.agent")

NodeFn = Callable[[AgentState, AgentContext], Awaitable[nodes.NodeResult]]
GraphNode = Callable[[AgentState, Runtime[AgentContext]], Awaitable[dict[str, object]]]


def instrumented(name: str, fn: NodeFn) -> GraphNode:
    """Emit node.started / node.completed / node.failed with duration and token usage."""

    async def run(state: AgentState, runtime: Runtime[AgentContext]) -> dict[str, object]:
        ctx = runtime.context
        meta: dict[str, object] = {
            "node": name,
            "step": state.get("current_step"),
            "attempt": state.get("attempt"),
        }
        await ctx.events.emit("node.started", meta)
        started = time.perf_counter()
        try:
            result = await fn(state, ctx)
        except Exception as exc:
            duration = round((time.perf_counter() - started) * 1000, 1)
            await ctx.events.emit(
                "node.failed", {**meta, "duration_ms": duration, "error": type(exc).__name__}
            )
            logger.exception("agent.node_failed", node=name, run_id=state.get("run_id"))
            raise
        duration = round((time.perf_counter() - started) * 1000, 1)
        usage: list[TokenUsage] = result.update.get("usage", [])  # type: ignore[assignment]
        tokens = {
            "prompt": sum(u.prompt_tokens for u in usage),
            "completion": sum(u.completion_tokens for u in usage),
        }
        await ctx.events.emit(
            "node.completed",
            {**meta, "duration_ms": duration, "tokens": tokens, "output": result.summary},
        )
        logger.info(
            "agent.node", node=name, run_id=state.get("run_id"), duration_ms=duration, **tokens
        )
        return result.update

    run.__name__ = name
    return run


# --------------------------------------------------------------------------------------------
# Routing (pure functions of state — unit-tested edge by edge)
# --------------------------------------------------------------------------------------------


def _can_repair(state: AgentState) -> bool:
    error = state.get("last_error")
    return (
        error is not None
        and error.retryable
        and state.get("attempt", 1) <= state.get("max_repairs", 3)
    )


def after_understand(state: AgentState) -> Literal["retrieve_schema", "respond"]:
    if state.get("intent") in (Intent.DATA, Intent.FOLLOW_UP):
        return "retrieve_schema"
    return "respond"


def after_resolve_time(state: AgentState) -> Literal["generate_sql", "respond"]:
    return "respond" if state.get("intent") is Intent.AMBIGUOUS else "generate_sql"


def after_candidate(state: AgentState) -> Literal["validate", "repair", "respond"]:
    """After generate_sql or repair."""
    if state.get("last_error") is None and state.get("candidate") is not None:
        return "validate"
    return "repair" if _can_repair(state) else "respond"


def after_validate(state: AgentState) -> Literal["execute", "repair", "respond"]:
    if state.get("last_error") is None:
        return "execute"
    return "repair" if _can_repair(state) else "respond"


def after_execute(state: AgentState) -> Literal["verify_results", "repair", "respond"]:
    if state.get("last_error") is None:
        return "verify_results"
    return "repair" if _can_repair(state) else "respond"


def after_verify(state: AgentState) -> Literal["generate_sql", "repair", "visualize"]:
    if state.get("last_error") is not None:
        return "repair"  # verify only reports an issue while the repair budget allows it
    if state.get("current_step", 0) < len(state.get("steps", [])):
        return "generate_sql"
    return "visualize"


def build_graph() -> CompiledStateGraph[AgentState, AgentContext, AgentState, AgentState]:
    graph = StateGraph(AgentState, context_schema=AgentContext)
    for name, fn in (
        ("understand", nodes.understand),
        ("retrieve_schema", nodes.retrieve_schema),
        ("plan", nodes.plan),
        ("resolve_time", nodes.resolve_time),
        ("generate_sql", nodes.generate_sql),
        ("validate", nodes.validate),
        ("execute", nodes.execute),
        ("repair", nodes.repair),
        ("verify_results", nodes.verify_results),
        ("visualize", nodes.visualize),
        ("explain", nodes.explain),
        ("remember", nodes.remember),
        ("respond", nodes.respond),
    ):
        graph.add_node(name, instrumented(name, fn))  # type: ignore[call-overload]

    graph.add_edge(START, "understand")
    graph.add_conditional_edges("understand", after_understand)
    graph.add_edge("retrieve_schema", "plan")
    graph.add_edge("plan", "resolve_time")
    graph.add_conditional_edges("resolve_time", after_resolve_time)
    graph.add_conditional_edges("generate_sql", after_candidate)
    graph.add_conditional_edges("repair", after_candidate)
    graph.add_conditional_edges("validate", after_validate)
    graph.add_conditional_edges("execute", after_execute)
    graph.add_conditional_edges("verify_results", after_verify)
    graph.add_edge("visualize", "explain")
    graph.add_edge("explain", "remember")
    graph.add_edge("remember", "respond")
    graph.add_edge("respond", END)
    return graph.compile(name="nexus-agent")


async def run_agent(
    graph: CompiledStateGraph[AgentState, AgentContext, AgentState, AgentState],
    ctx: AgentContext,
    *,
    run_id: str,
    question: str,
    history: list[HistoryTurn] | None = None,
) -> AgentState:
    initial: AgentState = {
        "run_id": run_id,
        "question": question,
        "history": history or [],
        "max_repairs": ctx.max_repairs,
        "attempt": 0,
        "current_step": 0,
        "last_error": None,
        "attempts": [],
        "results": [],
        "assumptions": [],
        "usage": [],
        "charts": [],
        "explanation": None,
    }
    final: AgentState = await graph.ainvoke(initial, context=ctx, config={"recursion_limit": 80})  # type: ignore[assignment]
    return final
