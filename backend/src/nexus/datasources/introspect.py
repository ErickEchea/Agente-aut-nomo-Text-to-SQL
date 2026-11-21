"""Schema catalog, table statistics and existing indexes for any supported engine.

PostgreSQL keeps its pg_catalog introspection (comments, exact constraint order); MySQL and SQLite
use SQLAlchemy's inspector. All queries here are fixed metadata queries built from catalog
identifiers (SQLAlchemy quotes them per dialect); none comes from the model.
"""

from __future__ import annotations

import re
from collections.abc import Iterable

from sqlalchemy import Connection, column, func, inspect, literal_column, select, table, text
from sqlalchemy.ext.asyncio import AsyncEngine
from sqlalchemy.sql.expression import ColumnClause

from nexus.agent.catalog import ColumnInfo, ForeignKey, SchemaCatalog, TableInfo, introspect
from nexus.datasources.dialects import Kind

TEXT_TYPE_PREFIXES = (
    "text", "character varying", "character", "varchar", "char", "nvarchar", "nchar",
    "tinytext", "mediumtext", "longtext", "string", "enum",
)  # fmt: skip
MAX_SAMPLE_DISTINCT = 25
MAX_SAMPLE_CHARS = 60


def is_text_type(data_type: str) -> bool:
    return data_type.lower().startswith(TEXT_TYPE_PREFIXES)


_SQLITE_TABLE_COMMENT = re.compile(r"CREATE TABLE[^(]*\(\s*--\s*(.+)")
_SQLITE_COLUMN_COMMENT = re.compile(r'^\s*["`\[]?(\w+)["`\]]?\s+[^-]*?--\s*(.+)$', re.MULTILINE)


def _sqlite_comments(sync_conn: Connection) -> dict[str, tuple[str, dict[str, str]]]:
    """SQLite has no COMMENT ON: read the common convention of trailing ``--`` comments in the
    CREATE TABLE text (first line: the table; each column line: that column)."""
    out: dict[str, tuple[str, dict[str, str]]] = {}
    rows = sync_conn.execute(text("SELECT name, sql FROM sqlite_master WHERE type = 'table'"))
    for name, ddl in rows:
        if not ddl:
            continue
        head = _SQLITE_TABLE_COMMENT.search(ddl)
        columns = {m.group(1): m.group(2).strip() for m in _SQLITE_COLUMN_COMMENT.finditer(ddl)}
        out[str(name)] = (head.group(1).strip() if head else "", columns)
    return out


def _schema_arg(kind: Kind, schema: str) -> str | None:
    """SQLite's only attached database is ``main``; the inspector wants None for it."""
    return None if kind == "sqlite" else schema


def _inspect_catalog(sync_conn: Connection, kind: Kind, schema: str) -> SchemaCatalog:
    inspector = inspect(sync_conn)
    target = _schema_arg(kind, schema)
    tables: dict[str, TableInfo] = {}
    comments = _sqlite_comments(sync_conn) if kind == "sqlite" else {}
    names = inspector.get_table_names(schema=target) + inspector.get_view_names(schema=target)
    for name in names:
        if kind == "sqlite" and name.startswith("sqlite_"):
            continue
        try:
            comment = inspector.get_table_comment(name, schema=target).get("text") or ""
        except NotImplementedError:
            comment = ""
        table_comment, column_comments = comments.get(name, ("", {}))
        comment = comment or table_comment
        columns = tuple(
            ColumnInfo(
                name=str(col["name"]),
                data_type=str(col["type"]).lower(),
                nullable=bool(col.get("nullable", True)),
                comment=str(col.get("comment") or column_comments.get(str(col["name"]), "")),
            )
            for col in inspector.get_columns(name, schema=target)
        )
        primary = tuple(
            inspector.get_pk_constraint(name, schema=target).get("constrained_columns") or ()
        )
        foreign: list[ForeignKey] = []
        for fk in inspector.get_foreign_keys(name, schema=target):
            for local, remote in zip(
                fk.get("constrained_columns") or [], fk.get("referred_columns") or [], strict=False
            ):
                foreign.append(ForeignKey(local, str(fk["referred_table"]), remote))
        tables[name] = TableInfo(
            name=name,
            comment=str(comment),
            columns=columns,
            primary_key=primary,
            foreign_keys=tuple(foreign),
        )
    return SchemaCatalog(schema=schema, tables=tables)


async def introspect_catalog(engine: AsyncEngine, kind: Kind, schema: str) -> SchemaCatalog:
    if kind == "postgresql":
        return await introspect(engine, schema)
    async with engine.connect() as conn:
        return await conn.run_sync(_inspect_catalog, kind, schema)


def _indexed(
    sync_conn: Connection, kind: Kind, schema: str, tables: Iterable[str]
) -> set[tuple[str, str]]:
    inspector = inspect(sync_conn)
    target = _schema_arg(kind, schema)
    leading: set[tuple[str, str]] = set()
    for name in tables:
        pk = inspector.get_pk_constraint(name, schema=target).get("constrained_columns") or []
        if pk:
            leading.add((name, str(pk[0])))
        for index in inspector.get_indexes(name, schema=target):
            cols = [c for c in index.get("column_names") or [] if c]
            if cols:
                leading.add((name, str(cols[0])))
    return leading


_PG_LEADING = text(
    """
    SELECT t.relname::text, a.attname::text
    FROM pg_catalog.pg_index i
    JOIN pg_catalog.pg_class t ON t.oid = i.indrelid
    JOIN pg_catalog.pg_namespace n ON n.oid = t.relnamespace
    JOIN pg_catalog.pg_attribute a ON a.attrelid = t.oid AND a.attnum = i.indkey[0]
    WHERE n.nspname = :schema
    """
)


async def existing_indexes(
    engine: AsyncEngine, kind: Kind, catalog: SchemaCatalog
) -> set[tuple[str, str]]:
    """(table, leading column) of every index and primary key: a column already usable as the
    first key of an index needs no new index."""
    async with engine.connect() as conn:
        if kind == "postgresql":
            # pg_catalog directly: the inspector's type introspection needs set_config(), which the
            # hardened reader role cannot call (ADR-0005).
            rows = (await conn.execute(_PG_LEADING, {"schema": catalog.schema})).all()
            return {(str(r[0]), str(r[1])) for r in rows}
        return await conn.run_sync(_indexed, kind, catalog.schema, list(catalog.tables))


_PG_ROWS = text(
    """
    SELECT c.relname AS table_name, greatest(c.reltuples, 0)::bigint AS rows
    FROM pg_catalog.pg_class c
    JOIN pg_catalog.pg_namespace n ON n.oid = c.relnamespace
    WHERE n.nspname = :schema AND c.relkind IN ('r', 'p')
    """
)
_MYSQL_ROWS = text(
    "SELECT table_name, table_rows FROM information_schema.tables WHERE table_schema = :schema"
)


async def row_estimates(engine: AsyncEngine, kind: Kind, catalog: SchemaCatalog) -> dict[str, int]:
    """Planner statistics where the engine keeps them; an exact count for SQLite files."""
    async with engine.connect() as conn:
        if kind == "postgresql":
            rows = (await conn.execute(_PG_ROWS, {"schema": catalog.schema})).all()
            return {str(r[0]): int(r[1]) for r in rows}
        if kind == "mysql":
            rows = (await conn.execute(_MYSQL_ROWS, {"schema": catalog.schema})).all()
            return {str(r[0]): int(r[1] or 0) for r in rows}
        counts: dict[str, int] = {}
        for name in catalog.tables:
            query = select(func.count()).select_from(table(name))
            counts[name] = int((await conn.execute(query)).scalar_one())
        return counts


async def collect_samples(
    engine: AsyncEngine, kind: Kind, catalog: SchemaCatalog, pii_columns: Iterable[str]
) -> dict[tuple[str, str], list[str]]:
    """Distinct values of low-cardinality text columns (never PII), most frequent first.

    These are database contents, i.e. untrusted: they are only ever rendered inside sanitized
    data blocks (see nexus.agent.prompts.data_block).
    """
    pii = {c.lower() for c in pii_columns}
    schema = _schema_arg(kind, catalog.schema)
    samples: dict[tuple[str, str], list[str]] = {}
    async with engine.connect() as conn:
        for info in catalog.tables.values():
            for col in info.columns:
                if f"{info.name}.{col.name}".lower() in pii or not is_text_type(col.data_type):
                    continue
                if col.name in info.primary_key:
                    continue
                target: ColumnClause[object] = column(col.name)
                count = func.count().label("n")
                query = (
                    select(target, count)
                    .select_from(table(info.name, schema=schema))
                    .where(target.is_not(None))
                    .group_by(target)
                    .order_by(literal_column("n").desc(), target)
                    .limit(MAX_SAMPLE_DISTINCT + 1)
                )
                rows = (await conn.execute(query)).all()
                if 0 < len(rows) <= MAX_SAMPLE_DISTINCT:
                    samples[(info.name, col.name)] = [str(r[0])[:MAX_SAMPLE_CHARS] for r in rows]
    return samples
