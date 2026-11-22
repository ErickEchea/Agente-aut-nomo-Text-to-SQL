"""Aggregate metrics and the default-model selection rule; the Markdown report."""

from __future__ import annotations

import datetime as dt

import pytest

from nexus.bench.golden import GoldenSet
from nexus.bench.metrics import is_eligible, percentile, select_default, summarize
from nexus.bench.report import render
from nexus.bench.runner import BenchConfig, ItemOutcome
from nexus.bench.store import RunRecord, read_records, write_record
from tests.unit.bench.test_golden import GOLDEN


def outcome(
    item: str, difficulty: str, *, correct: bool, ms: float, **extra: object
) -> ItemOutcome:
    values: dict[str, object] = {
        "item_id": item,
        "difficulty": difficulty,
        "question": f"¿{item}?",
        "status": "answered",
        "correct": correct,
        "reason": "ok" if correct else "row_values",
        "latency_ms": ms,
        "sql_attempts": 1,
        "first_attempt_ok": correct,
        "prompt_tokens": 1000,
        "completion_tokens": 100,
    }
    values.update(extra)
    return ItemOutcome.model_validate(values)


OUTCOMES = [
    outcome("e001", "easy", correct=True, ms=1000, recall_at_5=1.0, context_complete=True,
            nodes=[{"node": "generate_sql", "duration_ms": 400.0}, {"node": "generate_sql", "duration_ms": 200.0}]),
    outcome("e002", "easy", correct=False, ms=2000, recall_at_5=0.5, context_complete=False,
            repairs=2, explanation_fallback=True),
    outcome("m001", "medium", correct=True, ms=3000, repairs=1, explanation_fallback=False),
    outcome("a001", "ambiguous", correct=True, ms=500, status="clarification", sql_attempts=0,
            first_attempt_ok=False, reason="clarified"),
    outcome("h001", "hard", correct=False, ms=9000, status="failed", reason="status_failed"),
]  # fmt: skip


def test_percentile_nearest_rank() -> None:
    assert percentile([], 50) == 0.0
    assert percentile([5, 1, 3], 50) == 3
    assert percentile(list(range(1, 101)), 95) == 95


def test_summary_metrics() -> None:
    s = summarize(OUTCOMES)
    assert (s.items, s.correct, s.accuracy) == (5, 3, 0.6)
    assert s.by_difficulty["easy"].accuracy == 0.5 and s.by_difficulty["ambiguous"].correct == 1
    assert s.latency_p50_ms == 2000 and s.latency_p95_ms == 9000
    assert s.error_rate == 0.2  # one failed run
    assert s.first_attempt_rate == 0.5  # 2 of the 4 items that ran SQL
    assert s.recovery_rate == 0.5  # repaired: e002 (wrong) and m001 (right)
    assert s.grounding_fallback_rate == 0.5
    assert s.recall_at_5 == 0.75 and s.context_complete_rate == 0.5
    assert s.node_latency_ms == {"generate_sql": 600.0}
    assert s.reasons == {"row_values": 1, "status_failed": 1}
    assert s.tokens_per_question == 1100


def test_empty_summary_does_not_divide_by_zero() -> None:
    s = summarize([])
    assert s.accuracy == 0 and s.recovery_rate is None and s.recall_at_5 is None


def test_selection_prefers_accuracy_then_p95_within_two_points() -> None:
    def summary(accuracy: float, p95: float):  # type: ignore[no-untyped-def]
        return summarize(OUTCOMES).model_copy(update={"accuracy": accuracy, "latency_p95_ms": p95})

    assert select_default({}) is None
    assert select_default({"a": summary(0.80, 30_000), "b": summary(0.70, 5_000)}) == "a"
    assert select_default({"a": summary(0.80, 30_000), "b": summary(0.785, 5_000)}) == "b"
    assert select_default({"a": summary(0.80, 30_000), "b": summary(0.78, 5_000)}) == "b"
    assert select_default({"a": summary(0.80, 30_000), "b": summary(0.77, 5_000)}) == "a"
    # Eligibility comes first: a faster or more accurate configuration that fails h001 is out.
    tied = {"a": summary(0.80, 30_000), "b": summary(0.79, 5_000)}
    assert select_default(tied, eligible={"a"}) == "a"
    assert select_default(tied, eligible=set()) is None


def test_eligibility_needs_the_reference_question() -> None:
    assert is_eligible({"h001", "h031", "e001"})  # the reference question and its follow-up
    assert not is_eligible({"h001", "e001"})
    assert not is_eligible({"h031"})


@pytest.fixture
def records(tmp_path: object) -> list[RunRecord]:
    now = dt.datetime(2026, 11, 22, 12, tzinfo=dt.UTC)

    def record(
        name: str, think: bool | None, minutes: int, outcomes: list[ItemOutcome]
    ) -> RunRecord:
        return RunRecord(
            run_id=name,
            config=BenchConfig(name=name, model=f"{name}:1b", think=think),
            subset="full",
            dataset_version="1.0.0",
            git_sha="abc1234",
            started_at=now,
            finished_at=now + dt.timedelta(minutes=minutes),
            summary=summarize(outcomes),
            outcomes=outcomes,
        )

    return [
        record("fast", False, 1, OUTCOMES),
        record(
            "slow",
            None,
            2,
            [o.model_copy(update={"correct": True}) for o in OUTCOMES]
            + [outcome("h031", "hard", correct=True, ms=4000)],
        ),
    ]


def test_records_round_trip(tmp_path, records: list[RunRecord]) -> None:  # type: ignore[no-untyped-def]
    for record in records:
        write_record(tmp_path, record)
    (tmp_path / "retrieval-eval.json").write_text("[]", encoding="utf-8")  # other tools' files
    assert [r.config.name for r in read_records(tmp_path)] == ["fast", "slow"]


def test_report_renders_results_selection_and_misses(records: list[RunRecord]) -> None:
    golden = GoldenSet.load(GOLDEN)
    text = render(records, golden, hardware="GPU de prueba")
    assert "| **slow** |" in text and "**Selected: `slow`.**" in text
    assert "`fast:1b` (think off)" in text
    assert "GPU de prueba" in text and f"{len(golden.items)} questions" in text
    assert "## Questions the selected configuration got wrong (0)" in text
    assert "✗ (not eligible)" in text  # "fast" misses the reference question h001
    assert "generate_sql" in text


def test_report_without_runs() -> None:
    text = render([], GoldenSet.load(GOLDEN), hardware="x")
    assert "No completed full runs yet" in text
