"""Clause-by-clause explanation: segmentation spans, descriptions (es/en) and glossary rules."""

from __future__ import annotations

from nexus.agent.catalog import ColumnInfo, ForeignKey, SchemaCatalog, TableInfo
from nexus.agent.glossary import load_glossary
from nexus.sql.annotate import annotate, first_sentence
from tests.integration.conftest import REPO_ROOT


def _table(name: str, comment: str, *cols: tuple[str, str]) -> TableInfo:
    return TableInfo(
        name=name,
        comment=comment,
        columns=tuple(ColumnInfo(c, "integer", True, doc) for c, doc in cols),
        primary_key=(cols[0][0],),
        foreign_keys=(ForeignKey("venta_id", "ventas", "venta_id"),)
        if name == "detalle_ventas"
        else (),
    )


CATALOG = SchemaCatalog(
    "retail",
    {
        "ventas": _table(
            "ventas", "Cabecera de cada venta.", ("venta_id", "Ticket."), ("estado", "Estado de la venta."),
            ("fecha_venta", "Fecha de la venta."), ("sucursal_id", "Sucursal."),
        ),
        "detalle_ventas": _table(
            "detalle_ventas", "Líneas de cada venta.", ("detalle_id", "Línea."), ("venta_id", "Venta."),
            ("cantidad", "Unidades vendidas en la línea. Siempre positivas."), ("producto_id", "Producto."),
        ),
        "devoluciones": _table("devoluciones", "Devoluciones.", ("devolucion_id", "Id."), ("detalle_id", "Línea.")),
    },
)  # fmt: skip
GLOSSARY = load_glossary(REPO_ROOT / "data" / "glossary.yaml")

REVENUE = (
    "WITH lineas AS (SELECT dv.venta_id, SUM(dv.cantidad) AS u FROM retail.detalle_ventas AS dv "
    "GROUP BY dv.venta_id) "
    "SELECT v.sucursal_id, COUNT(*) AS n, COUNT(DISTINCT v.venta_id) AS tickets, AVG(l.u) AS prom, "
    "MIN(l.u) AS mn, MAX(l.u) AS mx, l.u * 2 AS doble FROM retail.ventas AS v "
    "LEFT JOIN lineas AS l ON l.venta_id = v.venta_id "
    "WHERE v.estado = 'completada' AND v.fecha_venta >= CAST('2026-07-01' AS DATE) "
    "AND v.fecha_venta < CAST('2026-10-01' AS DATE) "
    "AND NOT EXISTS (SELECT 1 FROM retail.devoluciones AS d WHERE d.detalle_id = l.venta_id) "
    "GROUP BY v.sucursal_id, l.u HAVING COUNT(*) > 2 ORDER BY n DESC, v.sucursal_id LIMIT 5"
)


def test_segments_cover_the_query_with_exact_spans() -> None:
    result = annotate(REVENUE, dialect="postgres", catalog=CATALOG, glossary=GLOSSARY)
    kinds = [(c.kind, c.scope) for c in result.clauses]
    assert kinds == [
        ("cte", "lineas"), ("select", "lineas"), ("from", "lineas"), ("group_by", "lineas"),
        ("select", ""), ("from", ""), ("join", ""), ("where", ""), ("group_by", ""),
        ("having", ""), ("order_by", ""), ("limit", ""),
    ]  # fmt: skip
    assert result.sql.splitlines()[0] == "WITH lineas AS ("
    assert result.sql.splitlines()[1].startswith("  SELECT dv.venta_id")  # CTE body indented
    for clause in result.clauses:
        assert result.sql[clause.start : clause.end].strip()
    join = next(c for c in result.clauses if c.kind == "join")
    assert result.sql[join.start : join.end].startswith("LEFT JOIN lineas")
    # Nothing is lost: the display text is the query re-flowed.
    assert "".join(result.sql.split()) == "".join(REVENUE.split())


def test_descriptions_in_spanish_with_catalog_comments_and_rules() -> None:
    question = "¿Qué sucursal generó mayores ingresos el último trimestre?"
    result = annotate(
        REVENUE, dialect="postgres", catalog=CATALOG, glossary=GLOSSARY, question=question
    )
    by = {(c.kind, c.scope): c for c in result.clauses}
    assert by[("cte", "lineas")].details == (
        "Calcula un resultado intermedio a partir de detalle_ventas, agregando por "
        "detalle_ventas.venta_id (venta).",
    )
    select = by[("select", "")].details
    assert "«n» = número de filas" in select
    assert "«tickets» = número de ventas.venta_id (ticket) distintos" in select
    assert "«prom» = promedio de l.u" not in select  # CTE columns are named by their alias
    assert any(line.startswith("«doble» = cálculo:") for line in select)
    assert by[("from", "")].details == ("Lee ventas (Cabecera de cada venta).",)
    assert by[("join", "")].title == "Unión (conserva todas las filas de la izquierda)"
    where = by[("where", "")]
    assert where.details[:3] == (
        "ventas.estado (estado de la venta) es «completada»",
        "ventas.fecha_venta (fecha de la venta) desde 2026-07-01",
        "ventas.fecha_venta (fecha de la venta) antes de 2026-10-01 (sin incluirlo)",
    )
    assert where.details[3].startswith(
        "Excluye las filas que tienen un registro relacionado en devoluciones"
    )
    assert where.rules and where.rules[0].startswith("Regla del glosario «ingresos»")
    assert by[("having", "")].details == ("COUNT(*) > 2",)
    assert by[("order_by", "")].details == (
        "n descendente",
        "ventas.sucursal_id (sucursal) ascendente",
    )
    assert by[("limit", "")].details == ("Devuelve como máximo 5 filas.",)


def test_english_and_other_predicates() -> None:
    sql = (
        "SELECT v.estado FROM retail.ventas AS v WHERE v.sucursal_id IN (1, 2) "
        "AND v.estado LIKE 'comp%' AND v.estado IS NULL AND NOT v.fecha_venta IS NULL "
        "AND v.venta_id BETWEEN 10 AND 20 AND v.estado <> 'anulada' AND v.venta_id > 3 "
        "AND v.venta_id <= 9 AND EXISTS (SELECT 1 FROM retail.devoluciones AS d WHERE d.detalle_id = v.venta_id) "
        "UNION SELECT 'x' LIMIT 3"
    )
    result = annotate(
        sql, dialect="postgres", catalog=CATALOG, glossary=GLOSSARY, locale="en", limit_added=True
    )
    where = next(c for c in result.clauses if c.kind == "where")
    assert where.title == "Filters"
    assert where.details == (
        "ventas.sucursal_id (sucursal) is one of: 1, 2",
        "ventas.estado (estado de la venta) matches “comp%”",
        "ventas.estado (estado de la venta) is empty",
        "ventas.fecha_venta (fecha de la venta) has a value",
        "ventas.venta_id (ticket) between 10 and 20",
        "ventas.estado (estado de la venta) different from anulada",
        "ventas.venta_id (ticket) after/greater than 3",
        "ventas.venta_id (ticket) up to 9",
        "Only rows with a related record in devoluciones (d.detalle_id = v.venta_id).",
    )
    assert any(c.kind == "set_op" for c in result.clauses)


def test_added_limit_is_explained() -> None:
    result = annotate(
        "SELECT v.venta_id FROM retail.ventas AS v LIMIT 1000",
        dialect="postgres",
        catalog=CATALOG,
        glossary=GLOSSARY,
        limit_added=True,
    )
    limit = result.clauses[-1]
    assert limit.details == (
        "Devuelve como máximo 1000 filas. NEXUS agregó este límite por seguridad.",
    )


def test_first_sentence_skips_abbreviations_and_decimals() -> None:
    assert first_sentence("Nombre de la categoría, p. ej. Electrónica. Otro dato.") == (
        "Nombre de la categoría, p. ej. Electrónica."
    )
    assert first_sentence("Agua mineral 1.5 L. Segunda.") == "Agua mineral 1.5 L."
    assert (
        first_sentence("Ingresos (e.g. net sales) only. More.") == "Ingresos (e.g. net sales) only."
    )
    assert first_sentence("Sin punto final") == "Sin punto final"
    assert first_sentence("Termina aquí.") == "Termina aquí."
