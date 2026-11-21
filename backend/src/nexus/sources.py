"""Read-only description of the configured data source, for the connections screen.

Built once at startup from the introspected catalog plus PostgreSQL's planner statistics
(``pg_class.reltuples``, an estimate that avoids a full ``count(*)`` over large tables).
Multi-database connections with encrypted credentials arrive in Phase 5 (ADR-0013).
"""

from __future__ import annotations

import datetime as dt
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

from nexus.agent.catalog import SchemaCatalog
from nexus.config import DatabaseSettings

_ROW_ESTIMATES_SQL = text(
    """
    SELECT c.relname AS table_name, greatest(c.reltuples, 0)::bigint AS rows
    FROM pg_catalog.pg_class c
    JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
    WHERE n.nspname = :schema AND c.relkind IN ('r', 'p')
    """
)


@dataclass(frozen=True, slots=True)
class TableSummary:
    name: str
    comment: str
    columns: int
    row_estimate: int
    foreign_keys: tuple[str, ...]


@dataclass(frozen=True, slots=True)
class DataSource:
    key: str
    dialect: str
    host: str
    port: int
    database: str
    schema: str
    user: str
    as_of: dt.date
    tables: tuple[TableSummary, ...]


async def describe_source(
    engine: AsyncEngine,
    db: DatabaseSettings,
    catalog: SchemaCatalog,
    *,
    key: str,
    as_of: dt.date,
) -> DataSource:
    async with engine.connect() as conn:
        rows = (await conn.execute(_ROW_ESTIMATES_SQL, {"schema": catalog.schema})).all()
    estimates = {r.table_name: int(r.rows) for r in rows}
    tables = tuple(
        TableSummary(
            name=t.name,
            comment=t.comment,
            columns=len(t.columns),
            row_estimate=estimates.get(t.name, 0),
            foreign_keys=tuple(sorted({fk.ref_table for fk in t.foreign_keys})),
        )
        for t in sorted(catalog.tables.values(), key=lambda t: t.name)
    )
    return DataSource(
        key=key,
        dialect=engine.dialect.name,
        host=db.host,
        port=db.port,
        database=db.name,
        schema=catalog.schema,
        user=db.user,
        as_of=as_of,
        tables=tables,
    )
