from pathlib import Path

import pytest

from nexus.agent.glossary import load_glossary

GLOSSARY = load_glossary(Path(__file__).resolve().parents[4] / "data" / "glossary.yaml")

NET_REVENUE_OK = (
    "SELECT s.nombre, SUM(dv.cantidad * dv.precio_unitario - dv.descuento) FROM retail.detalle_ventas dv "
    "JOIN retail.ventas v ON v.venta_id = dv.venta_id JOIN retail.sucursales s ON s.sucursal_id = v.sucursal_id "
    "WHERE v.estado = 'completada' AND NOT EXISTS "
    "(SELECT 1 FROM retail.devoluciones d WHERE d.detalle_id = dv.detalle_id) GROUP BY 1"
)
NET_REVENUE_NO_RETURNS = NET_REVENUE_OK.split(" AND NOT EXISTS", maxsplit=1)[0] + " GROUP BY 1"


def test_loads_terms_with_requirements() -> None:
    terms = {t.term: t for t in GLOSSARY.metrics}
    assert terms["ingresos"].requires is not None
    assert terms["ingresos"].requires.tables == ("devoluciones",)
    assert "ventas netas" in terms["ingresos"].synonyms
    assert "Moneda: USD." in GLOSSARY.render()


@pytest.mark.parametrize(
    ("question", "expected"),
    [
        ("¿Qué sucursal generó mayores ingresos?", ["sucursal", "ingresos"]),
        ("Ventas netas por región", ["ingresos", "región"]),
        ("Los cinco productos más vendidos", ["unidades vendidas"]),
        ("Ingresos brutos por mes", ["ventas brutas"]),  # longest match wins over "ingresos"
        ("¿Cuál es el producto más caro?", []),
    ],
)
def test_terms_in_question(question: str, expected: list[str]) -> None:
    assert sorted(t.term for t in GLOSSARY.terms_in(question)) == sorted(expected)


def test_violations_detect_missing_return_exclusion() -> None:
    q = "¿Qué sucursal generó mayores ingresos durante el último trimestre?"
    assert GLOSSARY.violations(q, NET_REVENUE_OK) == []
    problems = GLOSSARY.violations(q, NET_REVENUE_NO_RETURNS)
    assert len(problems) == 1
    assert "devoluciones" in problems[0]


def test_no_requirements_no_violations() -> None:
    assert GLOSSARY.violations("Ingresos brutos por mes", "SELECT 1") == []
    assert GLOSSARY.violations("¿Cuál es el producto más caro?", "SELECT 1") == []
