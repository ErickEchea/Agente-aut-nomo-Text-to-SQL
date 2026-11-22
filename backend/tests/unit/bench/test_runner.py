"""The runner scores real graph runs (scripted model, fake executor): answers, clarifications, errors."""

from __future__ import annotations

from pathlib import Path

from nexus.agent.graph import build_graph
from nexus.agent.state import (
    AgentContext,
    AuditSink,
    EventSink,
    MemorySink,
    Plan,
    SqlCandidate,
    Understanding,
)
from nexus.bench.compare import normalize
from nexus.bench.golden import (
    Difficulty,
    ExpectedResults,
    FrozenItem,
    FrozenResult,
    GoldenItem,
)
from nexus.bench.runner import BenchConfig, IsolatedMemory, load_configs, run_items
from nexus.llm import LLMError
from tests.unit.agent.fakes import FakeExecutor, ScriptedLLM, context, result

GRAPH = build_graph()
SQL = "SELECT canal, COUNT(*) AS ventas FROM retail.ventas GROUP BY canal"
ANSWER = GoldenItem(
    id="e900", question="¿Ventas por canal?", difficulty=Difficulty.EASY, gold_sql=SQL
)
AMBIGUOUS = GoldenItem(
    id="a900",
    question="¿Cuál es el mejor producto?",
    difficulty=Difficulty.AMBIGUOUS,
    expected_behavior="clarify",
)
EXPECTED = ExpectedResults(
    dataset_version="1.0.0",
    as_of="2026-11-01",
    items={
        "e900": FrozenItem(
            sql_sha256=ANSWER.sql_digest,
            results=(
                FrozenResult(
                    columns=("canal", "ventas"),
                    rows=(
                        (normalize("online"), normalize(10)),
                        (normalize("tienda"), normalize(90)),
                    ),
                ),
            ),
        )
    },
)


def factory(llm: ScriptedLLM, executor: FakeExecutor):  # type: ignore[no-untyped-def]
    async def make(events: EventSink, audit: AuditSink, memory: MemorySink) -> AgentContext:
        return context(llm, executor, events=events, audit=audit, memory=memory)

    return make


def answering_llm(rows_sql: str = SQL) -> ScriptedLLM:
    return ScriptedLLM(
        {
            Understanding: [
                Understanding(intent="data", standalone_question=ANSWER.question),
            ],
            Plan: [Plan(steps=[ANSWER.question])],
            SqlCandidate: [
                SqlCandidate(sql=rows_sql, tables_used=["ventas"], rationale="r", assumptions=[])
            ],
        }
    )


async def test_a_matching_answer_is_correct_and_measured() -> None:
    executor = FakeExecutor([("canal", result(("canal", "n"), [("tienda", 90), ("online", 10)]))])
    seen = []
    [outcome] = await run_items(
        GRAPH,
        factory(answering_llm(), executor),
        [ANSWER],
        EXPECTED,
        warmup=False,
        on_item=seen.append,
    )
    assert outcome.correct and outcome.reason == "ok" and outcome.status == "answered"
    assert outcome.sql_attempts == 1 and outcome.first_attempt_ok and outcome.repairs == 0
    assert outcome.llm_calls >= 3 and outcome.prompt_tokens > 0
    # The test retriever sends every table but ranks them alphabetically: ventas is 9th.
    assert outcome.recall_at_5 == 0.0 and outcome.context_complete is True
    assert {n["node"] for n in outcome.nodes} >= {"understand", "generate_sql", "execute"}
    assert seen == [outcome]


async def test_wrong_values_are_scored_incorrect() -> None:
    executor = FakeExecutor([("canal", result(("canal", "n"), [("tienda", 91), ("online", 10)]))])
    [outcome] = await run_items(
        GRAPH, factory(answering_llm(), executor), [ANSWER], EXPECTED, warmup=False
    )
    assert not outcome.correct and outcome.reason == "missing_column"


async def test_clarifying_an_ambiguous_question_is_correct() -> None:
    llm = ScriptedLLM(
        {
            Understanding: [
                Understanding(
                    intent="ambiguous",
                    standalone_question=AMBIGUOUS.question,
                    clarification_question="¿Mejor en qué?",
                    options=["unidades", "ingresos"],
                )
            ]
        }
    )
    [outcome] = await run_items(
        GRAPH, factory(llm, FakeExecutor([])), [AMBIGUOUS], EXPECTED, warmup=False
    )
    assert outcome.correct and outcome.reason == "clarified" and outcome.status == "clarification"
    assert outcome.recall_at_5 is None


async def test_answering_an_ambiguous_question_is_wrong() -> None:
    executor = FakeExecutor([("canal", result(("canal", "n"), [("tienda", 90)]))])
    llm = answering_llm()
    llm.script[Understanding] = [
        Understanding(intent="data", standalone_question=AMBIGUOUS.question)
    ]
    [outcome] = await run_items(GRAPH, factory(llm, executor), [AMBIGUOUS], EXPECTED, warmup=False)
    assert not outcome.correct and outcome.reason == "answered_ambiguous"


async def test_model_errors_become_failed_items_and_warmup_errors_are_tolerated() -> None:
    llm = ScriptedLLM(
        {Understanding: [LLMError("ollama unreachable"), LLMError("ollama unreachable")]}
    )
    [outcome] = await run_items(
        GRAPH, factory(llm, FakeExecutor([])), [ANSWER], EXPECTED, warmup=True
    )
    assert not outcome.correct and outcome.status == "error" and outcome.reason == "llm_error"
    assert outcome.error is not None and "unreachable" in outcome.error


async def test_isolated_memory_stores_nothing() -> None:
    assert await IsolatedMemory().remember(question="q", standalone="q", status="answered") is None


def test_configs(tmp_path: Path) -> None:
    path = tmp_path / "configs.yaml"
    path.write_text(
        "configs:\n  - {name: routed, model: a:1b, nodes: {plan: b:2b}, think: false}\n",
        encoding="utf-8",
    )
    config = load_configs(path)["routed"]
    assert config.models == ("a:1b", "b:2b")
    assert config.routing().plan == "b:2b" and config.routing().generate is None
    single = BenchConfig.single("qwen3:8b", think=False)
    assert single.name == "qwen3-8b" and single.think is False


async def test_follow_ups_are_asked_after_their_history_and_scored_alone() -> None:
    follow_up = ANSWER.model_copy(
        update={"id": "h900", "question": "¿Y en tienda?", "history": (ANSWER.question,)}
    )
    expected = ExpectedResults(
        dataset_version="1.0.0",
        as_of="2026-11-01",
        items={
            "h900": EXPECTED.items["e900"].model_copy(update={"sql_sha256": follow_up.sql_digest})
        },
    )
    llm = answering_llm()
    llm.script[Understanding].append(
        Understanding(intent="follow_up", standalone_question="¿Ventas por canal en tienda?")
    )
    llm.script[Plan].append(Plan(steps=["¿Ventas por canal en tienda?"]))
    llm.script[SqlCandidate].append(
        SqlCandidate(sql=SQL, tables_used=["ventas"], rationale="r", assumptions=[])
    )
    executor = FakeExecutor([("canal", result(("canal", "n"), [("tienda", 90), ("online", 10)]))])
    [outcome] = await run_items(GRAPH, factory(llm, executor), [follow_up], expected, warmup=False)
    assert outcome.correct and outcome.item_id == "h900"
    understand_calls = [m for name, m in llm.calls if name == "Understanding"]
    assert len(understand_calls) == 2
    assert ANSWER.question in understand_calls[1][1].content  # the history reached the model
    assert len(executor.executed) == 2  # history turn + follow-up, only the latter scored
