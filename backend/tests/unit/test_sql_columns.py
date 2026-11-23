"""Repair hints resolved against the catalog (nexus.sql.columns): unknown columns and comparisons
between incompatible types."""

from __future__ import annotations

from nexus.agent.catalog import ColumnInfo, SchemaCatalog, TableInfo
from nexus.sql.columns import SearchedSource, catalog_hint, type_mismatches, unknown_columns


def _type(column: str) -> str:
    if column.endswith("_id"):
        return "integer"
    return "date" if column.startswith("fecha") else "text"


def _table(name: str, cols: list[str]) -> TableInfo:
    return TableInfo(
        name=name,
        comment=f"Tabla {name}",
        columns=tuple(ColumnInfo(c, _type(c), True, "") for c in cols),
        primary_key=(cols[0],),
        foreign_keys=(),
    )


CATALOG = SchemaCatalog(
    schema="retail",
    tables={
        "clientes": _table("clientes", ["cliente_id", "provincia", "fecha_registro"]),
        "sucursales": _table("sucursales", ["sucursal_id", "provincia", "region_id"]),
        "regiones": _table("regiones", ["region_id", "nombre"]),
    },
)

# The query the 7B model repeated four times for "clientes nuevos por región este año".
REPEATED = """
WITH clientes_nuevos AS (
  SELECT region_id, COUNT(cliente_id) AS nuevos_registrados
  FROM retail.clientes
  WHERE fecha_registro >= DATE '2026-01-01' AND fecha_registro < DATE '2026-11-01'
  GROUP BY region_id
)
SELECT r.nombre AS region, cn.nuevos_registrados
FROM clientes_nuevos cn JOIN retail.regiones r ON cn.region_id = r.region_id
ORDER BY cn.nuevos_registrados DESC LIMIT 1
"""
PG_ERROR = 'column "region_id" does not exist'


def test_the_repeated_query_gets_where_the_column_lives() -> None:
    hint = catalog_hint(REPEATED, "postgres", CATALOG, PG_ERROR)
    assert hint == (
        "Según el catálogo del esquema:\n"
        "- La columna «region_id» no existe en retail.clientes "
        "(sus columnas son: cliente_id, provincia, fecha_registro).\n"
        "- «region_id» sí existe en: retail.regiones, retail.sucursales."
    )


def test_a_correct_query_with_ctes_aliases_and_joins_has_no_unknown_columns() -> None:
    sql = """
    WITH por_provincia AS (
      SELECT DISTINCT provincia, region_id FROM retail.sucursales
    ), nuevos AS (
      SELECT c.provincia, COUNT(*) AS total FROM retail.clientes c
      WHERE c.fecha_registro >= DATE '2026-01-01' GROUP BY c.provincia
    )
    SELECT r.nombre, SUM(n.total) AS clientes
    FROM nuevos n JOIN por_provincia p ON p.provincia = n.provincia
    JOIN retail.regiones r ON r.region_id = p.region_id
    GROUP BY r.nombre ORDER BY clientes DESC
    """
    assert unknown_columns(sql, "postgres", CATALOG) == []


def test_a_qualified_reference_is_checked_against_its_own_table_only() -> None:
    sql = (
        "SELECT r.nombre, COUNT(*) FROM retail.clientes c "
        "JOIN retail.regiones r ON r.region_id = c.region_id GROUP BY r.nombre"
    )
    [unknown] = unknown_columns(sql, "postgres", CATALOG)
    assert unknown.name == "region_id"
    assert unknown.searched == (
        SearchedSource("clientes", ("cliente_id", "provincia", "fecha_registro"), "table"),
    )
    assert unknown.owners == ("regiones", "sucursales")


def test_a_cte_hiding_a_real_table_is_pointed_out() -> None:
    """Second failure seen with the 7B model: a CTE named like a real table, then a column only
    the table has."""
    sql = (
        "WITH regiones AS (SELECT DISTINCT provincia, region_id FROM retail.sucursales), "
        "nuevos AS (SELECT c.cliente_id, c.provincia FROM retail.clientes AS c) "
        "SELECT r.nombre AS region, COUNT(n.cliente_id) AS total "
        "FROM regiones AS r JOIN nuevos AS n ON r.provincia = n.provincia GROUP BY r.nombre"
    )
    hint = catalog_hint(sql, "postgres", CATALOG, "column r.nombre does not exist")
    assert hint == (
        "Según el catálogo del esquema:\n"
        "- La columna «nombre» no existe en el CTE «regiones» definido en la consulta "
        "(solo devuelve: provincia, region_id); ese nombre oculta la tabla retail.regiones.\n"
        "- «nombre» sí existe en: retail.regiones."
    )


def test_subqueries_in_from_are_described_too() -> None:
    sql = "SELECT t.nombre FROM (SELECT provincia FROM retail.clientes) AS t"
    hint = catalog_hint(sql, "postgres", CATALOG, "column t.nombre does not exist")
    assert hint is not None
    assert "la subconsulta «t» definida en la consulta (solo devuelve: provincia)" in hint


def test_ctes_not_in_from_are_not_searched() -> None:
    sql = (
        "WITH otra AS (SELECT region_id FROM retail.sucursales) "
        "SELECT region_id FROM retail.clientes"
    )
    [unknown] = unknown_columns(sql, "postgres", CATALOG)
    assert [s.name for s in unknown.searched] == ["clientes"]


def test_an_unqualified_column_any_source_provides_is_fine() -> None:
    sql = "SELECT nombre, cliente_id FROM retail.clientes, retail.regiones"
    assert unknown_columns(sql, "postgres", CATALOG) == []


def test_a_column_no_table_has_is_reported_as_such() -> None:
    sql = "SELECT c.ciudad_residencia FROM retail.clientes c"
    hint = catalog_hint(sql, "postgres", CATALOG, "column c.ciudad_residencia does not exist")
    assert hint is not None
    assert "«ciudad_residencia» no existe en ninguna tabla del esquema." in hint


def test_only_the_columns_the_engine_named_are_reported() -> None:
    sql = "SELECT c.ciudad, c.barrio FROM retail.clientes c"
    hint = catalog_hint(sql, "postgres", CATALOG, "column c.barrio does not exist")
    assert hint is not None and "barrio" in hint and "ciudad" not in hint
    assert catalog_hint(sql, "postgres", CATALOG, "syntax error at or near") is None


def test_correlated_references_resolve_in_the_outer_scope() -> None:
    sql = (
        "SELECT c.cliente_id FROM retail.clientes c WHERE EXISTS ("
        "SELECT 1 FROM retail.sucursales s WHERE s.provincia = c.provincia)"
    )
    assert unknown_columns(sql, "postgres", CATALOG) == []


def test_star_selects_and_unknown_tables_never_produce_false_hints() -> None:
    star = "WITH t AS (SELECT * FROM retail.clientes) SELECT t.region_id FROM t"
    assert unknown_columns(star, "postgres", CATALOG) == []
    foreign = "SELECT x.region_id FROM retail.otra_tabla x"
    assert unknown_columns(foreign, "postgres", CATALOG) == []


def test_select_aliases_can_be_ordered_by() -> None:
    sql = (
        "SELECT provincia, COUNT(*) AS total FROM retail.clientes GROUP BY provincia ORDER BY total"
    )
    assert unknown_columns(sql, "postgres", CATALOG) == []


def test_sqlite_errors_name_the_column_too() -> None:
    sql = "SELECT region_id FROM clientes"
    hint = catalog_hint(sql, "sqlite", CATALOG, "no such column: region_id")
    assert hint is not None and "no existe en retail.clientes" in hint


def test_unparseable_sql_gives_no_hint() -> None:
    assert unknown_columns("SELECT FROM WHERE (", "postgres", CATALOG) == []
    assert type_mismatches("SELECT FROM WHERE (", "postgres", CATALOG) == []


# Third failure seen with the 7B model: the CTE drops provincia, so it joins on cliente_id.
MISMATCH = (
    "WITH clientes_nuevos AS (SELECT c.cliente_id, c.fecha_registro FROM retail.clientes AS c "
    "WHERE c.fecha_registro >= '2026-01-01') "
    "SELECT r.nombre AS region, COUNT(*) AS total FROM clientes_nuevos AS cn "
    "JOIN (SELECT DISTINCT provincia, region_id FROM retail.sucursales) AS pr "
    "ON pr.provincia = cn.cliente_id "
    "JOIN retail.regiones AS r ON r.region_id = pr.region_id GROUP BY r.nombre"
)


def test_a_comparison_of_text_with_integer_names_both_columns_and_their_sources() -> None:
    hint = catalog_hint(MISMATCH, "postgres", CATALOG, "operator does not exist: text = integer")
    assert hint == (
        "Según el catálogo del esquema:\n"
        "- Se comparan tipos distintos: pr.provincia (text, de retail.sucursales.provincia) con "
        "cn.cliente_id (integer, de retail.clientes.cliente_id).\n"
        "- «pr» es la subconsulta «pr» definida en la consulta (solo devuelve: provincia, "
        "region_id).\n"
        "- «cn» es el CTE «clientes_nuevos» definido en la consulta (solo devuelve: cliente_id, "
        "fecha_registro)."
    )


def test_compatible_comparisons_are_not_reported() -> None:
    sql = (
        "SELECT COUNT(*) FROM retail.clientes c JOIN retail.sucursales s "
        "ON s.provincia = c.provincia AND s.sucursal_id > c.cliente_id"
    )
    assert type_mismatches(sql, "postgres", CATALOG) == []


def test_a_mismatch_the_error_is_not_about_gives_no_hint() -> None:
    assert type_mismatches(MISMATCH, "postgres", CATALOG) != []
    assert catalog_hint(MISMATCH, "postgres", CATALOG, "division by zero") is None


def test_a_mismatch_between_two_tables_has_no_source_lines() -> None:
    sql = (
        "SELECT * FROM retail.clientes c JOIN retail.sucursales s ON s.provincia = c.fecha_registro"
    )
    hint = catalog_hint(sql, "postgres", CATALOG, "operator does not exist: text = date")
    assert hint is not None
    assert "s.provincia (text, de retail.sucursales.provincia)" in hint
    assert "c.fecha_registro (date, de retail.clientes.fecha_registro)" in hint
    assert "«s» es" not in hint and "«c» es" not in hint
