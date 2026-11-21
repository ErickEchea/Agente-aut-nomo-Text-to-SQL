"""MySQL 8.4 as a data source (ADR-0013), against a real server in a container."""

from __future__ import annotations

import time
from collections.abc import AsyncIterator, Iterator
from dataclasses import replace

import pymysql
import pytest
import pytest_asyncio
from pydantic import SecretStr
from testcontainers.core.container import DockerContainer

from nexus.agent.glossary import Glossary
from nexus.config import Settings
from nexus.datasources.introspect import (
    collect_samples,
    existing_indexes,
    introspect_catalog,
    row_estimates,
)
from nexus.datasources.registry import ConnectionSpec, create_source_engine, probe
from nexus.sql.annotate import annotate
from nexus.sql.executor import QueryExecutionError, ReadOnlyExecutor
from nexus.sql.optimizer import analyze
from nexus.sql.validator import SQLValidationError, ValidationPolicy, validate_sql

pytestmark = pytest.mark.integration

ROOT_PASSWORD = "root-test-password"
SETUP = [
    "CREATE DATABASE shop",
    "CREATE TABLE shop.customers (customer_id INT PRIMARY KEY, name VARCHAR(80) NOT NULL "
    "COMMENT 'Customer name', city VARCHAR(40) NOT NULL COMMENT 'City where the customer lives') "
    "COMMENT = 'Store customers'",
    "CREATE TABLE shop.orders (order_id INT PRIMARY KEY, customer_id INT NOT NULL COMMENT 'Buyer', "
    "status VARCHAR(20) NOT NULL COMMENT 'paid or cancelled', total DECIMAL(10,2) NOT NULL "
    "COMMENT 'Amount in USD', created_at DATE NOT NULL COMMENT 'Order date', "
    "CONSTRAINT orders_customer_fk FOREIGN KEY (customer_id) REFERENCES shop.customers (customer_id)) "
    "COMMENT = 'Customer orders'",
    "INSERT INTO shop.customers WITH RECURSIVE s(n) AS (SELECT 1 UNION ALL SELECT n + 1 FROM s "
    "WHERE n < 50) SELECT n, CONCAT('Cliente ', n), ELT(1 + n % 3, 'Quito', 'Guayaquil', 'Cuenca') FROM s",
    "SET SESSION cte_max_recursion_depth = 20000",
    "INSERT INTO shop.orders WITH RECURSIVE s(n) AS (SELECT 1 UNION ALL SELECT n + 1 FROM s "
    "WHERE n < 12000) SELECT n, 1 + n % 50, IF(n % 10 = 0, 'cancelled', 'paid'), (n % 1000) + 0.5, "
    "DATE_ADD('2025-01-01', INTERVAL n % 600 DAY) FROM s",
    "ANALYZE TABLE shop.orders, shop.customers",
    "CREATE USER 'reader'@'%' IDENTIFIED BY 'reader-pw'",
    "GRANT SELECT ON shop.* TO 'reader'@'%'",
    "CREATE USER 'writer'@'%' IDENTIFIED BY 'writer-pw'",
    "GRANT ALL PRIVILEGES ON shop.* TO 'writer'@'%'",
]


@pytest.fixture(scope="module")
def mysql_server() -> Iterator[tuple[str, int]]:
    container = (
        DockerContainer("mysql:8.4.9")
        .with_env("MYSQL_ROOT_PASSWORD", ROOT_PASSWORD)
        .with_exposed_ports(3306)
    )
    with container:
        host, port = container.get_container_host_ip(), int(container.get_exposed_port(3306))
        deadline = time.monotonic() + 180
        while True:
            try:
                conn = pymysql.connect(host=host, port=port, user="root", password=ROOT_PASSWORD)
                break
            except pymysql.err.OperationalError:
                if time.monotonic() > deadline:
                    raise
                time.sleep(1)
        with conn, conn.cursor() as cursor:
            for statement in SETUP:
                cursor.execute(statement)
            conn.commit()
        yield host, port


@pytest.fixture(scope="module")
def settings() -> Settings:
    return Settings(
        app_db={"host": "unused", "name": "x", "user": "x", "password": "x"},  # type: ignore[arg-type]
        demo_db={"host": "unused", "name": "x", "user": "x", "password": "x"},  # type: ignore[arg-type]
        security={"jwt_secret": SecretStr("s" * 40)},  # type: ignore[arg-type]
    )


@pytest.fixture(scope="module")
def reader(mysql_server: tuple[str, int]) -> ConnectionSpec:
    host, port = mysql_server
    return ConnectionSpec(
        key="shop",
        name="Shop",
        kind="mysql",
        database="shop",
        schema="shop",
        host=host,
        port=port,
        username="reader",
        password=SecretStr("reader-pw"),
    )


@pytest_asyncio.fixture(loop_scope="module", scope="module")
async def executor(reader: ConnectionSpec, settings: Settings) -> AsyncIterator[ReadOnlyExecutor]:
    engine = create_source_engine(reader, settings)
    yield ReadOnlyExecutor(engine, kind="mysql", statement_timeout_ms=800)
    await engine.dispose()


@pytest.mark.asyncio(loop_scope="module")
async def test_probe_detects_write_privileges(reader: ConnectionSpec, settings: Settings) -> None:
    ok = await probe(reader, settings)
    assert ok.ok and ok.tables == 2 and not ok.writable
    assert ok.version and ok.version.startswith("8.4")
    writer = replace(reader, username="writer", password=SecretStr("writer-pw"))
    risky = await probe(writer, settings)
    assert (
        risky.ok and risky.writable and any("ALL PRIVILEGES" in r for r in risky.writable_reasons)
    )
    wrong = await probe(replace(reader, password=SecretStr("nope")), settings)
    assert not wrong.ok and wrong.error


@pytest.mark.asyncio(loop_scope="module")
async def test_reads_with_dialect_functions_and_percent_signs(executor: ReadOnlyExecutor) -> None:
    result = await executor._execute_sql(
        "SELECT DATE_FORMAT(created_at, '%Y-%m') AS mes, COUNT(*) AS n FROM shop.orders "
        "WHERE status LIKE 'pa%' GROUP BY mes ORDER BY mes LIMIT 3"
    )
    assert result.columns == ("mes", "n") and result.rows[0][0] == "2025-01"


@pytest.mark.asyncio(loop_scope="module")
@pytest.mark.parametrize(
    "statement",
    ["DELETE FROM shop.orders", "UPDATE shop.orders SET total = 0", "DROP TABLE shop.orders"],
)
async def test_writes_fail_for_the_reader_and_inside_read_only_transactions(
    statement: str, executor: ReadOnlyExecutor, reader: ConnectionSpec, settings: Settings
) -> None:
    with pytest.raises(QueryExecutionError) as caught:
        await executor._execute_sql(statement)
    assert not caught.value.repairable
    # Even credentials that could write run read-only: DML *and* DDL are refused (a READ ONLY
    # transaction alone lets MySQL DDL through; the session-level flag does not).
    writer = replace(reader, username="writer", password=SecretStr("writer-pw"))
    engine = create_source_engine(writer, settings)
    try:
        with pytest.raises(QueryExecutionError) as blocked:
            await ReadOnlyExecutor(engine, kind="mysql")._execute_sql(statement)
        assert blocked.value.sqlstate == "MY1792"  # read-only, not just a privilege error
        count = await ReadOnlyExecutor(engine, kind="mysql")._execute_sql(
            "SELECT COUNT(*) FROM shop.orders"
        )
        assert count.rows == [(12000,)]
    finally:
        await engine.dispose()


@pytest.mark.asyncio(loop_scope="module")
async def test_slow_queries_hit_max_execution_time(executor: ReadOnlyExecutor) -> None:
    with pytest.raises(QueryExecutionError) as caught:
        await executor._execute_sql(
            "SELECT COUNT(*) FROM shop.orders a, shop.orders b, shop.orders c WHERE a.total < b.total"
        )
    assert caught.value.timeout and caught.value.sqlstate == "MY3024"
    unknown = None
    try:
        await executor._execute_sql("SELECT nope FROM shop.orders")
    except QueryExecutionError as exc:
        unknown = exc
    assert unknown is not None and unknown.repairable and unknown.sqlstate == "MY1054"


@pytest.mark.asyncio(loop_scope="module")
async def test_introspection_validation_optimizer_and_annotation(
    executor: ReadOnlyExecutor,
) -> None:
    engine = executor._engine
    catalog = await introspect_catalog(engine, "mysql", "shop")
    orders = catalog.tables["orders"]
    assert orders.comment == "Customer orders"
    assert next(c for c in orders.columns if c.name == "total").comment == "Amount in USD"
    assert [(f.column, f.ref_table) for f in orders.foreign_keys] == [("customer_id", "customers")]
    samples = await collect_samples(engine, "mysql", catalog, [])
    assert set(samples[("orders", "status")]) == {"paid", "cancelled"}
    rows = await row_estimates(engine, "mysql", catalog)
    assert rows["orders"] > 5_000
    indexes = await existing_indexes(engine, "mysql", catalog)
    assert ("orders", "customer_id") in indexes and ("orders", "created_at") not in indexes

    policy = ValidationPolicy(
        allowed_tables=catalog.table_names,
        allowed_schemas=frozenset({"shop"}),
        dialect="mysql",
        extra_allowed_functions=frozenset({"date_format"}),
    )
    for bad in ("SELECT SLEEP(5)", "SELECT * FROM mysql.user", "SELECT LOAD_FILE('/etc/passwd')"):
        with pytest.raises(SQLValidationError):
            validate_sql(bad, policy)
    query = validate_sql(
        "SELECT c.city, SUM(o.total) AS ingresos FROM shop.orders o "
        "JOIN shop.customers c ON c.customer_id = o.customer_id "
        "WHERE o.created_at >= DATE '2026-01-01' AND o.status = 'paid' GROUP BY c.city",
        policy,
    )
    assert (await executor.execute(query)).row_count == 3

    report = await analyze(
        executor,
        query,
        kind="mysql",
        dialect="mysql",
        catalog=catalog,
        rows=rows,
        indexes=indexes,
    )
    assert report.supports_costs and report.total_cost and report.total_cost > 0
    assert any(f.code == "full_scan" and f.table == "orders" for f in report.findings)
    suggested = {(s.table, s.columns) for s in report.suggestions}
    assert ("orders", ("created_at",)) in suggested
    assert all(s.ddl.startswith("CREATE INDEX `orders_") for s in report.suggestions)

    annotated = annotate(
        query.sql, dialect="mysql", catalog=catalog, glossary=Glossary.empty("mysql")
    )
    where = next(c for c in annotated.clauses if c.kind == "where")
    assert "orders.created_at (order date) desde 2026-01-01" in where.details
    assert "orders.status (paid or cancelled) es «paid»" in where.details
