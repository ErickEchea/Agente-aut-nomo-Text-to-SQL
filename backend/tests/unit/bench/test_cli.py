"""CLI helpers: leakage control, item selection, configuration resolution, the CI gate."""

from __future__ import annotations

import argparse
import datetime as dt
from pathlib import Path

import pytest

from nexus.bench.cli import BenchError, _resolve_configs, _select_items, check, find_overlaps
from nexus.bench.golden import GoldenSet
from nexus.bench.metrics import summarize
from nexus.bench.runner import BenchConfig, ItemOutcome
from nexus.bench.store import RunRecord, write_record
from tests.unit.agent.fakes import hash_embedding
from tests.unit.bench.test_golden import CONFIGS, GOLDEN


@pytest.fixture(scope="module")
def golden() -> GoldenSet:
    return GoldenSet.load(GOLDEN)


async def embed(text: str) -> list[float]:
    return hash_embedding(text)


async def test_overlaps_catch_repeats_and_paraphrases(golden: GoldenSet) -> None:
    items = golden.subset({"m001", "e001"})
    repeated = "¿CUÁLES fueron los cinco productos más vendidos durante el último trimestre"
    paraphrase = (
        "cuales fueron los cinco productos mas vendidos durante el ultimo trimestre de ventas"
    )
    unrelated = "Salario promedio de los bodegueros de Loja"
    leaks = await find_overlaps([repeated, paraphrase, unrelated], items, embed)
    assert any(leak.startswith("m001 = ") and "same text" in leak for leak in leaks)
    assert any(leak.startswith("m001 ≈ ") for leak in leaks)
    assert not any("Loja" in leak for leak in leaks)
    assert await find_overlaps([], items, embed) == []


def test_item_selection(golden: GoldenSet) -> None:
    assert len(_select_items(golden, "full", [])) == len(golden.items)
    assert [i.id for i in _select_items(golden, "ci", ["e001", "a001"])] == ["a001", "e001"]
    assert [i.id for i in _select_items(golden, "e002, m003", [])] == ["e002", "m003"]


def test_configuration_resolution() -> None:
    known = {"routed": BenchConfig(name="routed", model="a:1b", nodes={"plan": "b:1b"})}
    configs = _resolve_configs(["routed"], ["qwen3:8b"], False, known)
    assert [c.name for c in configs] == ["routed", "qwen3-8b"] and configs[1].think is False
    with pytest.raises(BenchError, match="unknown configuration"):
        _resolve_configs(["nope"], [], None, known)
    with pytest.raises(BenchError, match="nothing to run"):
        _resolve_configs([], [], None, known)


def _record(accuracy_hits: int, minutes: int) -> RunRecord:
    outcomes = [
        ItemOutcome(
            item_id=f"e{i:03d}",
            difficulty="easy",
            question="¿?",
            status="answered",
            correct=i < accuracy_hits,
            reason="ok",
            latency_ms=1.0,
        )
        for i in range(10)
    ]
    now = dt.datetime(2026, 11, 22, tzinfo=dt.UTC) + dt.timedelta(minutes=minutes)
    return RunRecord(
        run_id=str(minutes),
        config=BenchConfig(name="qwen2.5-coder-3b", model="qwen2.5-coder:3b"),
        subset="ci",
        dataset_version="1.0.0",
        git_sha=None,
        started_at=now,
        finished_at=now,
        summary=summarize(outcomes),
        outcomes=outcomes,
    )


def test_ci_gate_reads_the_newest_ci_run(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    args = argparse.Namespace(results=tmp_path, configs_file=CONFIGS)
    assert check(args) == 2  # nothing to judge
    write_record(tmp_path, _record(9, minutes=1))
    assert check(args) == 0
    write_record(tmp_path, _record(3, minutes=2))
    assert check(args) == 1
    assert "FAIL" in capsys.readouterr().out
