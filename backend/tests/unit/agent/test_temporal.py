from datetime import date, timedelta

import pytest
from hypothesis import given
from hypothesis import strategies as st

from nexus.agent.temporal import quarter_start, resolve

AS_OF = date(2026, 11, 1)  # the demo connection's data reference date

CASES = [
    # (question, expected (start, end_exclusive) of the single range, grain)
    ("¿Cuáles fueron los cinco productos más vendidos durante el último trimestre?", (date(2026, 7, 1), date(2026, 10, 1)), "quarter"),
    ("ventas del trimestre pasado", (date(2026, 7, 1), date(2026, 10, 1)), "quarter"),
    ("ingresos de este trimestre", (date(2026, 10, 1), date(2026, 11, 1)), "quarter"),
    ("¿y el mes pasado?", (date(2026, 10, 1), date(2026, 11, 1)), "month"),
    ("ventas de este mes", (date(2026, 11, 1), date(2026, 11, 1)), "month"),
    ("¿cuánto vendimos este año?", (date(2026, 1, 1), date(2026, 11, 1)), "year"),
    ("en lo que va del año", (date(2026, 1, 1), date(2026, 11, 1)), "year"),
    ("el año pasado", (date(2025, 1, 1), date(2026, 1, 1)), "year"),
    ("últimos 30 días", (date(2026, 10, 2), date(2026, 11, 1)), "day"),
    ("los últimos tres meses", (date(2026, 8, 1), date(2026, 11, 1)), "month"),
    ("últimas 2 semanas", (date(2026, 10, 18), date(2026, 11, 1)), "week"),
    ("la semana pasada", (date(2026, 10, 19), date(2026, 10, 26)), "week"),
    ("ayer", (date(2026, 10, 31), date(2026, 11, 1)), "day"),
    ("Q2 2025", (date(2025, 4, 1), date(2025, 7, 1)), "quarter"),
    ("en el T4 de 2024", (date(2024, 10, 1), date(2025, 1, 1)), "quarter"),
    ("segundo trimestre de 2026", (date(2026, 4, 1), date(2026, 7, 1)), "quarter"),
    ("primer semestre de 2025", (date(2025, 1, 1), date(2025, 7, 1)), "semester"),
    ("ventas en marzo de 2025", (date(2025, 3, 1), date(2025, 4, 1)), "month"),
    ("¿qué pasó en diciembre?", (date(2025, 12, 1), date(2026, 1, 1)), "month"),
    ("durante 2025", (date(2025, 1, 1), date(2026, 1, 1)), "year"),
    ("sales last quarter", (date(2026, 7, 1), date(2026, 10, 1)), "quarter"),
    ("revenue in May 2026", (date(2026, 5, 1), date(2026, 6, 1)), "month"),
]  # fmt: skip


@pytest.mark.parametrize(("question", "expected", "grain"), CASES)
def test_resolves_expression(question: str, expected: tuple[date, date], grain: str) -> None:
    resolution = resolve(question, AS_OF)
    assert len(resolution.ranges) == 1, resolution.ranges
    r = resolution.ranges[0]
    assert (r.start, r.end) == expected
    assert r.grain == grain


def test_reference_question_assumption_is_human_readable() -> None:
    resolution = resolve(
        "¿Cuáles fueron los cinco productos más vendidos durante el último trimestre y qué "
        "sucursal generó mayores ingresos?",
        AS_OF,
    )
    assert resolution.assumptions == (
        "«último trimestre» = 1 jul 2026 – 30 sep 2026",
        "Fecha de referencia de los datos: 1 nov 2026",
    )
    assert resolution.ranges[0].sql_hint("v.fecha_venta") == (
        "v.fecha_venta >= DATE '2026-07-01' AND v.fecha_venta < DATE '2026-10-01'"
    )


def test_same_period_last_year_shifts_the_first_range() -> None:
    resolution = resolve("ventas del último trimestre vs el mismo periodo del año anterior", AS_OF)
    assert [(r.start, r.end) for r in resolution.ranges] == [
        (date(2026, 7, 1), date(2026, 10, 1)),
        (date(2025, 7, 1), date(2025, 10, 1)),
    ]


def test_multiple_expressions_keep_text_order() -> None:
    resolution = resolve("compara enero de 2026 con el año pasado", AS_OF)
    assert [r.grain for r in resolution.ranges] == ["month", "year"]


def test_no_expression_and_vague_terms() -> None:
    assert resolve("¿cuál es el producto más caro?", AS_OF).ranges == ()
    assert resolve("¿qué se vendió recientemente?", AS_OF).vague_terms == ("recientemente",)


Q3 = resolve("último trimestre", AS_OF).ranges


@pytest.mark.parametrize(
    ("follow_up", "expected"),
    [
        ("¿y en el trimestre anterior?", (date(2026, 4, 1), date(2026, 7, 1))),
        ("¿y el mes anterior?", (date(2026, 6, 1), date(2026, 7, 1))),
        ("¿y el mismo periodo del año anterior?", (date(2025, 7, 1), date(2025, 10, 1))),
        ("and the previous quarter?", (date(2026, 4, 1), date(2026, 7, 1))),
        ("¿y en Q1 2025?", (date(2025, 1, 1), date(2025, 4, 1))),  # explicit wins
    ],
)
def test_follow_ups_resolve_relative_to_the_previous_period(
    follow_up: str, expected: tuple[date, date]
) -> None:
    ranges = resolve(follow_up, AS_OF, previous=Q3).ranges
    assert [(r.start, r.end) for r in ranges] == [expected]


def test_without_history_anterior_means_last_closed_period() -> None:
    (r,) = resolve("el trimestre anterior", AS_OF).ranges
    assert (r.start, r.end) == (date(2026, 7, 1), date(2026, 10, 1))


def test_english_may_is_not_a_month_without_year() -> None:
    assert resolve("may I see total sales by branch", AS_OF).ranges == ()


@given(st.dates(min_value=date(2000, 1, 2), max_value=date(2099, 12, 31)))
def test_last_quarter_is_the_closed_quarter_before_as_of(as_of: date) -> None:
    r = resolve("último trimestre", as_of).ranges[0]
    assert r.end == quarter_start(as_of)
    assert r.start.day == 1 and r.start.month in (1, 4, 7, 10)
    assert 89 <= (r.end - r.start).days <= 92
    assert r.end <= as_of


@given(st.dates(min_value=date(2000, 1, 2), max_value=date(2099, 12, 31)))
def test_ranges_are_half_open_and_never_in_the_future(as_of: date) -> None:
    for text in ("mes pasado", "este año", "últimos 7 días", "la semana pasada", "año pasado"):
        for r in resolve(text, as_of).ranges:
            assert r.start <= r.end <= as_of + timedelta(days=1)
