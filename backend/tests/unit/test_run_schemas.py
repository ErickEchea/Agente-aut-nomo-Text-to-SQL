"""The typed run result accepts every shape the agent stores (old, partial and complete)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from nexus.runs.schemas import RunResult


def test_cancelled_and_failed_runs_only_need_a_status() -> None:
    cancelled = RunResult.model_validate({"status": "cancelled", "answer": ""})
    assert cancelled.results == [] and cancelled.charts == [] and cancelled.explanation is None
    assert cancelled.tokens.calls == 0


def test_complete_result_round_trips() -> None:
    stored = {
        "status": "answered",
        "answer": "Samborondón lideró.",
        "intent": "data",
        "standalone_question": "¿Qué sucursal vendió más?",
        "steps": ["¿Qué sucursal vendió más?"],
        "assumptions": ["«último trimestre» = 1 jul 2026 – 30 sep 2026"],
        "time_ranges": [
            {
                "expression": "último trimestre",
                "start": "2026-07-01",
                "end": "2026-10-01",
                "grain": "quarter",
            }
        ],
        "clarification": None,
        "results": [
            {
                "index": 0,
                "question": "¿Qué sucursal vendió más?",
                "sql": "SELECT 1",
                "columns": ["sucursal", "ingresos"],
                "rows": [["Samborondón", 299672.19]],
                "row_count": 1,
            }
        ],
        "attempts": [
            {
                "step": 0,
                "attempt": 1,
                "sql": "SELECT 1",
                "outcome": "rejected",
                "error": {"kind": "validation", "code": "glossary", "message": "returns"},
            }
        ],
        "tokens": {"prompt": 10, "completion": 5, "calls": 2},
        "charts": [
            {
                "kind": "kpi",
                "step": 0,
                "candidates": ["kpi", "table"],
                "reason": "single row",
                "kpis": [{"label": "ingresos", "value": 299672.19}],
            }
        ],
        "explanation": {"headline": "Samborondón lideró.", "bullets": [], "caveats": []},
        "retrieval": {"strategy": "hybrid", "tables": ["ventas"]},
    }
    result = RunResult.model_validate(stored)
    assert result.results[0].rows == [["Samborondón", 299672.19]]
    assert result.attempts[0].error is not None and result.attempts[0].error.code == "glossary"
    assert RunResult.model_validate(result.model_dump(mode="json")) == result


def test_unknown_status_is_rejected() -> None:
    with pytest.raises(ValidationError):
        RunResult.model_validate({"status": "maybe"})
