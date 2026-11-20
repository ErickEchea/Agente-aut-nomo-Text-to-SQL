import pytest

from nexus.agent.grounding import allowed_values, extract_numbers, ungrounded

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
