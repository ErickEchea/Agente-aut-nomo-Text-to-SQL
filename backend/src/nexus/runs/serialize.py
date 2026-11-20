"""The agent's final state as the JSON stored on ``runs.result`` and returned by the API."""

from __future__ import annotations

from typing import Any

from nexus.agent.state import AgentState, SqlAttempt, StepResult


def _attempt(a: SqlAttempt) -> dict[str, Any]:
    return {
        "step": a.step,
        "attempt": a.attempt,
        "sql": a.sql,
        "outcome": a.outcome,
        "error": None
        if a.error is None
        else {"kind": a.error.kind, "code": a.error.code, "message": a.error.message},
        "duration_ms": a.duration_ms,
    }


def _step(r: StepResult) -> dict[str, Any]:
    return {
        "index": r.index,
        "question": r.question,
        "sql": r.sql,
        "columns": list(r.columns),
        "rows": [list(row) for row in r.rows],
        "row_count": r.row_count,
        "truncated": r.truncated,
        "tables": list(r.tables),
        "rationale": r.rationale,
        "assumptions": list(r.assumptions),
        "warnings": list(r.warnings),
    }


def serialize_final(state: AgentState) -> dict[str, Any]:
    clarification = state.get("clarification")
    time = state.get("time")
    usage = state.get("usage", [])
    intent = state.get("intent")
    context = state.get("schema_context")
    return {
        "status": str(state.get("status", "failed")),
        "answer": state.get("answer", ""),
        "intent": intent.value if intent is not None else None,
        "standalone_question": state.get("standalone_question"),
        "steps": state.get("steps", []),
        "assumptions": state.get("assumptions", []),
        "time_ranges": [
            {
                "expression": r.expression,
                "start": r.start.isoformat(),
                "end": r.end.isoformat(),
                "grain": r.grain,
            }
            for r in (time.ranges if time is not None else ())
        ],
        "clarification": None
        if clarification is None
        else {"question": clarification.question, "options": list(clarification.options)},
        "results": [_step(r) for r in state.get("results", [])],
        "attempts": [_attempt(a) for a in state.get("attempts", [])],
        "tokens": {
            "prompt": sum(u.prompt_tokens for u in usage),
            "completion": sum(u.completion_tokens for u in usage),
            "calls": len(usage),
        },
        "charts": [c.model_dump(mode="json", exclude_none=True) for c in state.get("charts", [])],
        "explanation": _explanation(state),
        "retrieval": context.summary() if context is not None else None,
    }


def _explanation(state: AgentState) -> dict[str, Any] | None:
    result = state.get("explanation")
    if result is None:
        return None
    return {
        **result.explanation.model_dump(),
        "grounded": result.grounded,
        "fallback": result.fallback,
        "attempts": result.attempts,
        "rejected_numbers": list(result.ungrounded),
    }
