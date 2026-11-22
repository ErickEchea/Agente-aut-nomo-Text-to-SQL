import pytest

from nexus.agent.grounding import (
    allowed_values,
    extract_numbers,
    format_number,
    localize_numbers,
    quantity_values,
    ungrounded,
)

ROWS = [
    [("Agua mineral 1.5 L", 4768), ("Pollo entero por kg Mr. Pollo", 2707)],
    [("Samborondón", 299672.19)],
]
ALLOWED = allowed_values(
    ROWS,
    texts=["los cinco productos más vendidos del último trimestre", "1 jul 2026 – 30 sep 2026"],
)


@pytest.mark.parametrize(
    "text",
    [
        "Samborondón lideró con $299.672,19 en ingresos.",
        "Samborondón lideró con USD 299,672.19.",
        "Samborondón facturó unos 299,7 mil dólares.",
        "Samborondón facturó $0,3 M.",
        "El agua mineral de 1.5 L vendió 4.768 unidades.",
        "El agua mineral vendió 4768 unidades y el pollo 2,707.",
        "Los cinco productos más vendidos entre el 1 de julio y el 30 de septiembre de 2026.",
        "Hay 2 productos en la lista.",
        "Samborondón: 299 672,19 USD.",
    ],
)
def test_grounded_summaries_pass(text: str) -> None:
    assert ungrounded(text, ALLOWED) == []


@pytest.mark.parametrize(
    ("text", "bad"),
    [
        ("Samborondón facturó $312.450,00.", ["312.450,00"]),
        ("El agua representa el 37 % de las ventas.", ["37 %"]),
        ("Se vendieron 4.800 unidades de agua.", ["4.800"]),
        ("Las ventas crecieron 12,5 % frente al trimestre anterior.", ["12,5 %"]),
    ],
)
def test_invented_numbers_are_flagged(text: str, bad: list[str]) -> None:
    assert ungrounded(text, ALLOWED) == bad


def test_ambiguous_thousands_and_decimal_readings() -> None:
    (token,) = extract_numbers("4.768")
    values = {round(v, 3) for v, _ in token.readings}
    assert values == {4.768, 4768.0}
    (token,) = extract_numbers("1.234.567,89")
    assert [round(v, 2) for v, _ in token.readings] == [1234567.89]


def test_displayed_precision_sets_the_tolerance() -> None:
    allowed = {299672.19}
    assert ungrounded("299.672", allowed) == []  # rounded to units
    assert ungrounded("299.670", allowed) == ["299.670"]  # off by 2 units, not rounding


# ---- localized numbers (the model mixes "291,168.77" and "291.168,77" in one answer) --------------

KEEP = ["Agua mineral 1.5 L", "Pollo entero por kg Mr. Pollo", "Samborondón"]
QUANTITIES = quantity_values(
    [(("producto", "unidades"), ROWS[0]), (("sucursal", "ingresos"), ROWS[1])]
)


@pytest.mark.parametrize(
    ("text", "locale", "expected"),
    [
        ("Samborondón facturó $299,672.19.", "es", "Samborondón facturó $299.672,19."),
        ("Samborondón facturó $299.672,19.", "en", "Samborondón facturó $299,672.19."),
        (
            "Se vendieron 4,768 unidades y 2707 de pollo.",
            "es",
            "Se vendieron 4.768 unidades y 2.707 de pollo.",
        ),
        ("Se vendieron 4.768 unidades.", "en", "Se vendieron 4,768 unidades."),
        (
            "Unos $299.672 en ingresos.",
            "es",
            "Unos $299.672 en ingresos.",
        ),  # rounded: decimals kept as shown
        ("Facturó $0.3 M.", "es", "Facturó $0,3 M."),
        (
            "Agua mineral 1.5 L: 4768 unidades.",
            "es",
            "Agua mineral 1.5 L: 4.768 unidades.",
        ),  # names untouched
        ("agua mineral 1.5 l lideró.", "es", "agua mineral 1.5 l lideró."),  # case-insensitive
        (
            "Del 1 de julio al 30 de septiembre de 2026.",
            "es",
            "Del 1 de julio al 30 de septiembre de 2026.",
        ),
        (
            "Se inventaron 312.450,00 dólares.",
            "en",
            "Se inventaron 312.450,00 dólares.",
        ),  # ungrounded
    ],
)
def test_grounded_numbers_follow_the_locale(text: str, locale: str, expected: str) -> None:
    assert localize_numbers(text, QUANTITIES, locale, keep=KEEP) == expected  # type: ignore[arg-type]


def test_ambiguous_readings_are_left_as_written() -> None:
    allowed = {1.5, 1500.0}
    assert localize_numbers("Llegaron 1.500 cajas.", allowed, "en") == "Llegaron 1.500 cajas."


def test_format_number_matches_the_ui() -> None:
    assert format_number(1234567.891, 2, "es") == "1.234.567,89"
    assert format_number(1234567.891, 2, "en") == "1,234,567.89"
    assert format_number(4768, 0, "es") == "4.768"
    assert format_number(12.5, 1, "es") == "12,5"


def test_quantities_skip_year_columns_and_years_in_the_text() -> None:
    rows = [(2025, 2098), (2026, 1834)]
    quantities = quantity_values([(("anio", "unidades"), rows)])
    assert quantities == {2098.0, 1834.0}
    text = "En 2025 se vendieron 2098 unidades y en 2026, 1834."
    assert (
        localize_numbers(text, quantities, "es")
        == "En 2025 se vendieron 2.098 unidades y en 2026, 1.834."
    )
