"""PostgreSQL optimizer with HypoPG on the seeded demo (Phase 5 exit criterion)."""

from __future__ import annotations

import pytest

from nexus.agent.catalog import introspect
from nexus.config import DatabaseSettings
from nexus.datasources.introspect import existing_indexes, row_estimates
from nexus.db.engines import create_engine
from nexus.demo.loader import LoadResult
from nexus.sql.executor import ReadOnlyExecutor
from nexus.sql.optimizer import analyze
from nexus.sql.validator import SQLValidationError, ValidationPolicy, validate_sql

pytestmark = [pytest.mark.integration, pytest.mark.asyncio(loop_scope="module")]

PLANTED = "SELECT SUM(dv.cantidad) AS unidades FROM retail.detalle_ventas AS dv WHERE dv.producto_id = 189"


async def test_optimizer_finds_the_planted_missing_index(
    reader_db: DatabaseSettings, seeded: LoadResult
) -> None:
    engine = create_engine(reader_db, application_name="test-optimizer")
    try:
        catalog = await introspect(engine, "retail")
        rows = await row_estimates(engine, "postgresql", catalog)
        indexes = await existing_indexes(engine, "postgresql", catalog)
        assert ("detalle_ventas", "producto_id") not in indexes  # ADR-0017 anomaly #7
        assert ("detalle_ventas", "venta_id") in indexes
        policy = ValidationPolicy(allowed_tables=catalog.table_names)
        query = validate_sql(PLANTED, policy)
        executor = ReadOnlyExecutor(engine, kind="postgresql")

        report = await analyze(
            executor,
            query,
            kind="postgresql",
            dialect="postgres",
            catalog=catalog,
            rows=rows,
            indexes=indexes,
        )
        assert report.supports_costs and report.total_cost
        assert any(s.operation == "Seq Scan" and s.table == "detalle_ventas" for s in report.plan)
        (suggestion,) = report.suggestions
        assert (suggestion.table, suggestion.columns) == ("detalle_ventas", ("producto_id",))
        assert suggestion.ddl == 'CREATE INDEX ON "retail"."detalle_ventas" ("producto_id")'
        assert suggestion.used_by_planner is True
        assert suggestion.cost_before == report.total_cost
        assert suggestion.cost_after is not None and suggestion.cost_after < suggestion.cost_before
        assert (suggestion.improvement or 0) > 0.3  # ~45 % at test scale (10k lines)
        assert any(f.code == "missing_index" and f.severity == "high" for f in report.findings)

        # Nothing persists: the hypothetical index lived in a discarded backend.
        for _ in range(3):
            plain = await executor.explain(query)
            assert "<" not in str(plain.plan)
            assert "Seq Scan" in str(plain.plan)
        # The index was never really created.
        assert ("detalle_ventas", "producto_id") not in await existing_indexes(
            engine, "postgresql", catalog
        )
    finally:
        await engine.dispose()


async def test_model_written_sql_cannot_reach_hypopg(reader_db: DatabaseSettings) -> None:
    policy = ValidationPolicy(allowed_tables=frozenset({"ventas"}))
    for sql in (
        "SELECT * FROM hypopg.hypopg_list_indexes",
        "SELECT hypopg_create_index('CREATE INDEX ON retail.ventas (canal)')",
        "SELECT hypopg.hypopg_reset()",
    ):
        with pytest.raises(SQLValidationError):
            validate_sql(sql, policy)
