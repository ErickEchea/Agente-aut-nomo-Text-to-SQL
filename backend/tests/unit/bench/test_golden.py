"""The committed golden set: size and balance, validity, frozen answers in sync, CI subset."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from nexus.bench.cli import load_ci
from nexus.bench.golden import Difficulty, ExpectedResults, GoldenItem, GoldenSet
from nexus.bench.runner import load_configs
from nexus.demo import DATASET_VERSION
from nexus.sql.validator import ValidationPolicy, validate_sql
from tests.integration.conftest import REPO_ROOT

GOLDEN = REPO_ROOT / "bench" / "golden"
CONFIGS = REPO_ROOT / "bench" / "configs.yaml"
TABLES = frozenset(
    {"regiones", "sucursales", "categorias", "productos", "clientes", "empleados",
     "ventas", "detalle_ventas", "inventario", "devoluciones"}
)  # fmt: skip


@pytest.fixture(scope="module")
def golden() -> GoldenSet:
    return GoldenSet.load(GOLDEN)


def test_at_least_120_questions_across_all_difficulties(golden: GoldenSet) -> None:
    counts = golden.counts()
    assert len(golden.items) >= 120
    assert all(counts[d.value] >= 10 for d in Difficulty), counts


def test_frozen_answers_match_the_gold_sql_and_dataset(golden: GoldenSet) -> None:
    expected = ExpectedResults.load(GOLDEN)
    assert expected.dataset_version == DATASET_VERSION
    assert expected.as_of == "2026-11-01"
    assert expected.stale(golden) == [], "gold SQL changed without `make bench-freeze`"
    answering = {i.id for i in golden.items if i.answers}
    assert set(expected.items) == answering
    for item in golden.items:
        if item.answers:
            assert len(expected.items[item.id].results) == len(item.gold_sql)


def test_every_gold_query_passes_the_agents_validator(golden: GoldenSet) -> None:
    policy = ValidationPolicy(allowed_tables=TABLES, max_rows=1000)
    for item in golden.items:
        for sql in item.gold_sql:
            validate_sql(sql, policy)
        if item.answers:
            assert item.gold_tables <= TABLES, item.id


def test_questions_are_unique(golden: GoldenSet) -> None:
    questions = [item.question.strip().lower() for item in golden.items]
    assert len(set(questions)) == len(questions)


def test_gold_tables_skip_ctes() -> None:
    item = GoldenItem(
        id="h999",
        question="¿Prueba?",
        difficulty=Difficulty.HARD,
        gold_sql="WITH t AS (SELECT * FROM retail.ventas) SELECT * FROM t JOIN retail.sucursales s ON true",
    )
    assert item.gold_tables == {"ventas", "sucursales"}
    assert (
        item.sql_digest
        == item.model_copy(update={"gold_sql": (" ".join(item.gold_sql[0].split()),)}).sql_digest
    )


@pytest.mark.parametrize(
    "bad",
    [
        {"id": "x1", "question": "¿Pregunta?", "difficulty": "easy", "gold_sql": "SELECT 1"},
        {"id": "m001", "question": "¿Pregunta?", "difficulty": "easy", "gold_sql": "SELECT 1"},
        {"id": "e001", "question": "¿Pregunta?", "difficulty": "easy"},
        {
            "id": "a001",
            "question": "¿Pregunta?",
            "difficulty": "ambiguous",
            "expected_behavior": "clarify",
            "gold_sql": "SELECT 1",
        },
    ],
)
def test_invalid_items_are_rejected(bad: dict[str, object]) -> None:
    with pytest.raises(ValidationError):
        GoldenItem.model_validate(bad)


def test_duplicated_ids_are_rejected(tmp_path: Path) -> None:
    body = 'difficulty: easy\nitems:\n  - {id: e001, question: "¿A?", gold_sql: "SELECT 1"}\n'
    (tmp_path / "a.yaml").write_text(body, encoding="utf-8")
    (tmp_path / "b.yaml").write_text(body, encoding="utf-8")
    with pytest.raises(ValueError, match="duplicated"):
        GoldenSet.load(tmp_path)


def test_configs_and_ci_gate_are_consistent(golden: GoldenSet) -> None:
    configs = load_configs(CONFIGS)
    ci = load_ci(CONFIGS)
    assert ci.config in configs
    assert set(ci.items) <= {item.id for item in golden.items}
    assert len(ci.items) >= 10
    assert 0 < ci.min_accuracy <= 1, "the CI threshold must be calibrated (ADR-0022)"
    assert configs["routed-qwen3-coder"].routing().generate is None  # SQL stays on the default
    assert configs["routed-qwen3-coder"].routing().plan == "qwen3:8b"
    assert configs["qwen3-8b"].think is False
