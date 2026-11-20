"""Schema catalog: what the agent knows about a data source, introspected from the database itself.

Table/column comments are first-class: they carry the business meaning the model needs. In Phase 2
the whole (small) schema is sent; Phase 3 replaces the selection with hybrid retrieval.
"""

from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass

from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine


@dataclass(frozen=True, slots=True)
class ColumnInfo:
    name: str
    data_type: str
    nullable: bool
    comment: str


@dataclass(frozen=True, slots=True)
class ForeignKey:
    column: str
    ref_table: str
    ref_column: str


@dataclass(frozen=True, slots=True)
class TableInfo:
    name: str
    comment: str
    columns: tuple[ColumnInfo, ...]
    primary_key: tuple[str, ...]
    foreign_keys: tuple[ForeignKey, ...]


@dataclass(frozen=True, slots=True)
class SchemaCatalog:
    schema: str
    tables: dict[str, TableInfo]

    @property
    def table_names(self) -> frozenset[str]:
        return frozenset(self.tables)

    def render(self, tables: Iterable[str] | None = None) -> str:
        """Compact, comment-rich DDL for the prompt (only the requested tables, if given)."""
        names = sorted(self.tables) if tables is None else [t for t in tables if t in self.tables]
        blocks: list[str] = []
        for name in names:
            table = self.tables[name]
            lines = [f"-- {table.comment}", f"TABLE {self.schema}.{name} ("]
            for col in table.columns:
                flags = []
                if col.name in table.primary_key:
                    flags.append("PK")
                fk = next((f for f in table.foreign_keys if f.column == col.name), None)
                if fk:
                    flags.append(f"FK→{fk.ref_table}.{fk.ref_column}")
                if not col.nullable and col.name not in table.primary_key:
                    flags.append("NOT NULL")
                flag_text = f" [{', '.join(flags)}]" if flags else ""
                lines.append(f"  {col.name} {col.data_type}{flag_text} -- {col.comment}")
            lines.append(")")
            blocks.append("\n".join(lines))
        return "\n\n".join(blocks)


_COLUMNS_SQL = text(
    """
    SELECT c.relname AS table_name,
           coalesce(obj_description(c.oid, 'pg_class'), '') AS table_comment,
           a.attname AS column_name,
           format_type(a.atttypid, a.atttypmod) AS data_type,
           NOT a.attnotnull AS nullable,
           coalesce(col_description(c.oid, a.attnum), '') AS column_comment,
           a.attnum
    FROM pg_class c
    JOIN pg_namespace n ON n.oid = c.relnamespace
    JOIN pg_attribute a ON a.attrelid = c.oid AND a.attnum > 0 AND NOT a.attisdropped
    WHERE n.nspname = :schema AND c.relkind IN ('r', 'v', 'm', 'p')
      AND has_table_privilege(c.oid, 'SELECT')
    ORDER BY c.relname, a.attnum
    """
)

_CONSTRAINTS_SQL = text(
    """
    SELECT tc.relname AS table_name, con.contype,
           a.attname AS column_name,
           rc.relname AS ref_table, ra.attname AS ref_column
    FROM pg_constraint con
    JOIN pg_class tc ON tc.oid = con.conrelid
    JOIN pg_namespace n ON n.oid = tc.relnamespace
    CROSS JOIN LATERAL unnest(con.conkey) WITH ORDINALITY AS k(attnum, ord)
    JOIN pg_attribute a ON a.attrelid = tc.oid AND a.attnum = k.attnum
    LEFT JOIN pg_class rc ON rc.oid = con.confrelid
    LEFT JOIN pg_attribute ra ON ra.attrelid = con.confrelid AND ra.attnum = con.confkey[k.ord]
    WHERE n.nspname = :schema AND con.contype IN ('p', 'f')
    ORDER BY tc.relname, con.contype, k.ord
    """
)


async def introspect(engine: AsyncEngine, schema: str = "retail") -> SchemaCatalog:
    async with engine.connect() as conn:
        column_rows = (await conn.execute(_COLUMNS_SQL, {"schema": schema})).all()
        constraint_rows = (await conn.execute(_CONSTRAINTS_SQL, {"schema": schema})).all()

    comments: dict[str, str] = {}
    columns: dict[str, list[ColumnInfo]] = {}
    for row in column_rows:
        comments[row.table_name] = row.table_comment
        columns.setdefault(row.table_name, []).append(
            ColumnInfo(row.column_name, row.data_type, bool(row.nullable), row.column_comment)
        )
    pks: dict[str, list[str]] = {}
    fks: dict[str, list[ForeignKey]] = {}
    for row in constraint_rows:
        if row.contype == "p":
            pks.setdefault(row.table_name, []).append(row.column_name)
        else:
            fks.setdefault(row.table_name, []).append(
                ForeignKey(row.column_name, row.ref_table, row.ref_column)
            )
    tables = {
        name: TableInfo(
            name=name,
            comment=comments[name],
            columns=tuple(cols),
            primary_key=tuple(pks.get(name, [])),
            foreign_keys=tuple(fks.get(name, [])),
        )
        for name, cols in columns.items()
    }
    return SchemaCatalog(schema=schema, tables=tables)
