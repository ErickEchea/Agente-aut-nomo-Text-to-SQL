"""Execution-accuracy comparison: canonical cells, column matching, order, periods, multi-part answers."""

from __future__ import annotations

from decimal import Decimal

import pytest

from nexus.bench.compare import PredictedResult, compare, normalize, score_answer
from nexus.bench.golden import FrozenResult


def gold(columns: tuple[str, ...], rows: list[tuple[object, ...]]) -> FrozenResult:
    return FrozenResult(
        columns=columns, rows=tuple(tuple(normalize(c) for c in row) for row in rows)
    )


@pytest.mark.parametrize(
    ("value", "token"),
    [
        (None, "∅"),
        (True, "b:true"),
        (5, "n:5.00"),
        (5.0, "n:5.00"),
        (Decimal("299672.185"), "n:299672.19"),  # half-up, not banker's rounding
        (-0.001, "n:0.00"),
        ("12.5", "n:12.50"),
        ("2025-07-01", "d:2025-07-01"),
        ("2025-07-01T00:00:00", "d:2025-07-01"),
        ("2025-07-01T10:15:00", "t:2025-07-01T10:15:00"),
        ("  Samborondón ", "s:Samborondón"),
        ("QUI-01", "s:QUI-01"),
        (float("nan"), "s:nan"),
    ],
)
def test_normalize(value: object, token: str) -> None:
    assert normalize(value) == token


def test_columns_match_by_values_not_names_or_order_and_extras_are_tolerated() -> None:
    expected = gold(("nombre", "ingresos"), [("Samborondón", 299672.19)])
    outcome = compare(
        expected,
        ("sucursal_id", "ingresos_netos", "sucursal"),
        [(8, 299672.1912, "Samborondón")],
        order_matters=True,
    )
    assert outcome.ok and outcome.mapping == (2, 1)


def test_rows_are_a_multiset_unless_order_matters() -> None:
    expected = gold(("canal", "ventas"), [("online", 10), ("tienda", 90)])
    reversed_rows = [("tienda", 90), ("online", 10)]
    assert compare(expected, ("canal", "ventas"), reversed_rows, order_matters=False).ok
    ranked = compare(expected, ("canal", "ventas"), reversed_rows, order_matters=True)
    assert not ranked.ok and ranked.reason == "order"


@pytest.mark.parametrize(
    ("rows", "reason"),
    [
        ([("online", 10)], "row_count"),
        ([("online", 10), ("tienda", 91)], "missing_column"),
        ([("online", 90), ("tienda", 10)], "row_values"),  # right values, wrong pairing
    ],
)
def test_failures_explain_themselves(rows: list[tuple[object, ...]], reason: str) -> None:
    expected = gold(("canal", "ventas"), [("online", 10), ("tienda", 90)])
    outcome = compare(expected, ("canal", "ventas"), rows, order_matters=False)
    assert not outcome.ok and outcome.reason == reason


def test_no_columns_is_no_result() -> None:
    assert compare(gold(("n",), [(1,)]), (), [], order_matters=False).reason == "no_result"


def test_percent_and_fraction_are_not_equivalent() -> None:
    expected = gold(("porcentaje",), [(8.51,)])
    assert not compare(expected, ("pct",), [(0.0851,)], order_matters=False).ok


@pytest.mark.parametrize(
    "month_cells",
    [
        ["2026-01-01T00:00:00", "2026-02-01T00:00:00"],
        ["2026-01", "2026-02"],
        [1, 2],
        ["enero", "febrero"],
        ["2026-01-01", "2026-02-01"],
    ],
)
def test_month_periods_accept_equivalent_spellings(month_cells: list[object]) -> None:
    expected = gold(("mes", "ventas"), [("2026-01-01T00:00:00", 5), ("2026-02-01T00:00:00", 7)])
    rows = [(month_cells[0], 5), (month_cells[1], 7)]
    assert compare(expected, ("periodo", "ventas"), rows, order_matters=False).ok


def test_month_numbers_need_a_single_year() -> None:
    expected = gold(("mes", "n"), [("2025-12-01T00:00:00", 1), ("2026-01-01T00:00:00", 2)])
    assert not compare(expected, ("mes", "n"), [(12, 1), (1, 2)], order_matters=False).ok
    assert compare(expected, ("mes", "n"), [("2025-12", 1), ("2026-01", 2)], order_matters=False).ok


@pytest.mark.parametrize(
    "year_cells", [[2025, 2026], ["2025", "2026"], ["2025-01-01", "2026-01-01"]]
)
def test_year_periods_accept_equivalent_spellings(year_cells: list[object]) -> None:
    expected = gold(
        ("anio", "ingresos"), [("2025-01-01T00:00:00", 100.5), ("2026-01-01T00:00:00", 80)]
    )
    rows = [(year_cells[0], 100.5), (year_cells[1], 80)]
    assert compare(expected, ("year", "ingresos"), rows, order_matters=False).ok


def test_value_columns_do_not_get_period_equivalence() -> None:
    expected = gold(("fecha_apertura",), [("2025-07-01",)])
    assert not compare(expected, ("fecha",), [("2025-07",)], order_matters=False).ok


def test_two_gold_columns_cannot_share_one_predicted_column() -> None:
    expected = gold(("a", "b"), [(1, 1)])
    assert not compare(expected, ("x",), [(1,)], order_matters=False).ok
    assert compare(expected, ("x", "y"), [(1, 1)], order_matters=False).ok


def test_multi_part_answers_need_a_distinct_step_per_part() -> None:
    top = gold(("nombre", "unidades"), [("Agua", 10), ("Leche", 8)])
    branch = gold(("nombre", "ingresos"), [("Samborondón", 5.5)])
    steps = [
        PredictedResult(("nombre", "unidades"), [("Agua", 10), ("Leche", 8)]),
        PredictedResult(("sucursal", "ingresos"), [("Samborondón", 5.5)]),
    ]
    assert score_answer([top, branch], steps, order_matters=True).ok
    assert not score_answer([top, branch], steps[:1], order_matters=True).ok
    assert score_answer([top], [], order_matters=False).reason == "no_result"


def test_the_closest_failure_is_reported() -> None:
    expected = gold(("nombre", "unidades"), [("Agua", 10), ("Leche", 8)])
    steps = [
        PredictedResult(("x",), [(1,)]),
        PredictedResult(("nombre", "unidades"), [("Leche", 8), ("Agua", 10)]),
    ]
    assert score_answer([expected], steps, order_matters=True).reason == "order"
