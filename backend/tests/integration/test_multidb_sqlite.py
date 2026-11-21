"""SQLite as a data source (ADR-0013): read-only file, timeouts, introspection, optimizer."""

from __future__ import annotations

from collections.abc import AsyncIterator
from pathlib import Path

import pytest
import pytest_asyncio
from pydantic import SecretStr

from nexus.agent.glossary import Glossary
from nexus.config import Settings
from nexus.datasources.introspect import (
    collect_samples,
    existing_indexes,
    introspect_catalog,
    row_estimates,
)
from nexus.datasources.registry import ConnectionSpec, SourceError, create_source_engine, probe
from nexus.demo.sqlite_export import export_sqlite
from nexus.sql.annotate import annotate
from nexus.sql.executor import QueryExecutionError, ReadOnlyExecutor
from nexus.sql.optimizer import analyze
from nexus.sql.validator import SQLValidationError, ValidationPolicy, validate_sql
from tests.integration.conftest import SQL_DIR

pytestmark = pytest.mark.integration

FILE = "retail.sqlite"


@pytest.fixture(scope="module")
def sqlite_dir(tmp_path_factory: pytest.TempPathFactory) -> Path:
    base = tmp_path_factory.mktemp("sqlite")
    export_sqlite(base / FILE, SQL_DIR, scale=0.02)
    (tmp_path_factory.mktemp("outside") / "secret.sqlite").write_bytes(b"")
    return base


@pytest.fixture(scope="module")
def settings(sqlite_dir: Path) -> Settings:
    return Settings(
        app_db={"host": "unused", "name": "x", "user": "x", "password": "x"},  # type: ignore[arg-type]
        demo_db={"host": "unused", "name": "x", "user": "x", "password": "x"},  # type: ignore[arg-type]
        security={"jwt_secret": SecretStr("s" * 40)},  # type: ignore[arg-type]
        connections={"sqlite_dir": sqlite_dir},  # type: ignore[arg-type]
    )


SPEC = ConnectionSpec(key="mini", name="Mini", kind="sqlite", database=FILE, schema="main")


@pytest_asyncio.fixture(loop_scope="module", scope="module")
async def executor(settings: Settings) -> AsyncIterator[ReadOnlyExecutor]:
    engine = create_source_engine(SPEC, settings)
    yield ReadOnlyExecutor(engine, kind="sqlite", statement_timeout_ms=300)
    await engine.dispose()


async def test_probe_and_path_confinement(settings: Settings) -> None:
    result = await probe(SPEC, settings)
    assert result.ok and result.tables == 10 and not result.writable
    assert result.version and result.version.startswith("3.")
    escape = ConnectionSpec(
        key="x", name="x", kind="sqlite", database="../outside0/secret.sqlite", schema="main"
    )
    outside = await probe(escape, settings)
    assert not outside.ok and "directorio" in (outside.error or "")
    with pytest.raises(SourceError):
        create_source_engine(
            ConnectionSpec(
                key="y", name="y", kind="sqlite", database="missing.sqlite", schema="main"
            ),
            settings,
        )


@pytest.mark.asyncio(loop_scope="module")
async def test_introspection_keeps_comments_keys_and_indexes(executor: ReadOnlyExecutor) -> None:
    engine = executor._engine
    catalog = await introspect_catalog(engine, "sqlite", "main")
    sales = catalog.tables["detalle_ventas"]
    assert sales.comment.startswith("Líneas de cada venta")
    assert {(f.column, f.ref_table) for f in sales.foreign_keys} >= {("producto_id", "productos")}
    assert next(c for c in sales.columns if c.name == "cantidad").comment
    indexes = await existing_indexes(engine, "sqlite", catalog)
    assert ("detalle_ventas", "venta_id") in indexes
    assert ("detalle_ventas", "producto_id") not in indexes  # the planted gap (ADR-0017 #7)
    assert (await row_estimates(engine, "sqlite", catalog))["detalle_ventas"] > 5_000
    samples = await collect_samples(engine, "sqlite", catalog, ["clientes.email"])
    assert "completada" in samples[("ventas", "estado")]
    assert ("clientes", "email") not in samples


@pytest.mark.asyncio(loop_scope="module")
@pytest.mark.parametrize(
    "statement",
    [
        "DELETE FROM detalle_ventas",
        "INSERT INTO regiones VALUES (99, 'x', 'y')",
        "CREATE TABLE pwned (x INTEGER)",
        "UPDATE productos SET precio_lista = 0",
        "PRAGMA query_only = OFF; DELETE FROM regiones",
    ],
)
async def test_the_file_cannot_be_written_even_without_the_validator(
    executor: ReadOnlyExecutor, statement: str
) -> None:
    with pytest.raises(QueryExecutionError) as caught:
        await executor._execute_sql(statement)
    assert not caught.value.repairable


@pytest.mark.asyncio(loop_scope="module")
async def test_slow_queries_are_interrupted(executor: ReadOnlyExecutor) -> None:
    slow = (
        "WITH RECURSIVE n(i) AS (SELECT 1 UNION ALL SELECT i + 1 FROM n WHERE i < 100000000) "
        "SELECT count(*) FROM n"
    )
    with pytest.raises(QueryExecutionError) as caught:
        await executor._execute_sql(slow)
    assert caught.value.timeout and caught.value.sqlstate == "SQLITE_INTERRUPT"
    # The connection is usable afterwards (the progress handler was reset).
    assert (await executor._execute_sql("SELECT 1")).rows == [(1,)]


@pytest.mark.asyncio(loop_scope="module")
async def test_validator_optimizer_and_annotation(executor: ReadOnlyExecutor) -> None:
    engine = executor._engine
    catalog = await introspect_catalog(engine, "sqlite", "main")
    policy = ValidationPolicy(
        allowed_tables=catalog.table_names,
        allowed_schemas=frozenset({"main"}),
        dialect="sqlite",
        extra_allowed_functions=frozenset({"strftime"}),
    )
    with pytest.raises(SQLValidationError):
        validate_sql("SELECT * FROM retail.ventas", policy)  # wrong schema for this source
    query = validate_sql(
        "SELECT strftime('%Y-%m', v.fecha_venta) AS mes, SUM(dv.cantidad) AS unidades "
        "FROM main.detalle_ventas dv JOIN main.ventas v ON v.venta_id = dv.venta_id "
        "WHERE dv.producto_id = 189 AND v.fecha_venta >= '2026-07-01' GROUP BY 1 ORDER BY 1",
        policy,
    )
    result = await executor.execute(query)
    assert result.columns == ("mes", "unidades") and result.row_count > 0

    # The planted case: totals for one product scan every sale line without an index.
    query = validate_sql(
        "SELECT p.nombre, SUM(dv.cantidad) AS unidades FROM main.detalle_ventas dv "
        "JOIN main.productos p ON p.producto_id = dv.producto_id "
        "WHERE dv.producto_id = 189 GROUP BY p.nombre",
        policy,
    )

    report = await analyze(
        executor,
        query,
        kind="sqlite",
        dialect="sqlite",
        catalog=catalog,
        rows=await row_estimates(engine, "sqlite", catalog),
        indexes=await existing_indexes(engine, "sqlite", catalog),
    )
    assert not report.supports_costs
    assert any(f.code == "full_scan" and f.table == "detalle_ventas" for f in report.findings)
    (suggestion,) = report.suggestions
    assert (suggestion.table, suggestion.columns) == ("detalle_ventas", ("producto_id",))
    assert suggestion.ddl == (
        'CREATE INDEX "detalle_ventas_producto_id_idx" ON "detalle_ventas" ("producto_id")'
    )

    annotated = annotate(
        query.sql, dialect="sqlite", catalog=catalog, glossary=Glossary.empty("sqlite")
    )
    kinds = [c.kind for c in annotated.clauses]
    assert kinds == ["select", "from", "join", "where", "group_by", "limit"]
    where = next(c for c in annotated.clauses if c.kind == "where")
    assert annotated.sql[where.start : where.end].startswith("WHERE dv.producto_id = 189")
    assert where.details == ("detalle_ventas.producto_id (producto vendido) = 189",)
