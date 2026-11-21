"""``nexus-export-sqlite``: the retail demo dataset as a SQLite file (a second engine to try).

Same seeded generator as the PostgreSQL demo, at a smaller scale by default. Primary and foreign
keys come from ``schema.sql`` / ``constraints.sql``; every table and column keeps its comment
as a trailing ``--`` comment in the DDL, which NEXUS reads back from ``sqlite_master``. Secondary
indexes mirror ``constraints.sql`` — including the deliberately missing one on
``detalle_ventas(producto_id)`` (ADR-0017 anomaly #7), so the optimizer has something to find.
"""

from __future__ import annotations

import argparse
import re
import sqlite3
import sys
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

from nexus.demo.generator import DEFAULT_SEED, GeneratorConfig, generate
from nexus.demo.tables import Column, Table

_COMMENT = re.compile(r"COMMENT ON (TABLE|COLUMN) ([\w.]+) IS '((?:[^']|'')*)';")
_FK = re.compile(
    r"ALTER TABLE (\w+) ADD CONSTRAINT \w+ FOREIGN KEY \((\w+)\) REFERENCES (\w+) \((\w+)\);"
)
_INDEX = re.compile(r"CREATE INDEX (\w+) ON (\w+) \(([\w, ]+)\);")
_PK = re.compile(r"^\s*(\w+)\s+\w+[^,]*PRIMARY KEY", re.MULTILINE)

_TYPES = {
    "int": "INTEGER",
    "text": "TEXT",
    "date": "TEXT",  # ISO 'YYYY-MM-DD'
    "timestamp": "TEXT",  # ISO 'YYYY-MM-DD HH:MM:SS'
    "money": "REAL",
    "bool": "INTEGER",
}


@dataclass(slots=True)
class _Ddl:
    tables: dict[str, str] = field(default_factory=dict)
    columns: dict[tuple[str, str], str] = field(default_factory=dict)
    primary: dict[str, str] = field(default_factory=dict)
    foreign: dict[tuple[str, str], tuple[str, str]] = field(default_factory=dict)
    indexes: list[tuple[str, str, str]] = field(default_factory=list)


def _read_ddl(sql_dir: Path) -> _Ddl:
    schema = (sql_dir / "schema.sql").read_text(encoding="utf-8")
    constraints = (sql_dir / "constraints.sql").read_text(encoding="utf-8")
    ddl = _Ddl()
    for kind, target, text in _COMMENT.findall(schema):
        comment = text.replace("''", "'")
        if kind == "TABLE":
            ddl.tables[target] = comment
        else:
            table, column = target.split(".", 1)
            ddl.columns[(table, column)] = comment
    for block in re.findall(r"CREATE TABLE (\w+) \((.*?)\n\);", schema, re.DOTALL):
        found = _PK.search(block[1])
        if found:
            ddl.primary[block[0]] = found.group(1)
    for table, column, ref_table, ref_column in _FK.findall(constraints):
        ddl.foreign[(table, column)] = (ref_table, ref_column)
    ddl.indexes = [(n, t, c) for n, t, c in _INDEX.findall(constraints)]
    return ddl


def _one_line(text: str) -> str:
    return " ".join(text.split())


def _create(table: Table, ddl: _Ddl) -> str:
    lines = [f'CREATE TABLE "{table.name}" ( -- {_one_line(ddl.tables.get(table.name, ""))}']
    columns: list[Column] = list(table.columns)
    for i, column in enumerate(columns):
        parts = [f'"{column.name}"', _TYPES[column.kind]]
        if ddl.primary.get(table.name) == column.name:
            parts.append("PRIMARY KEY")
        elif not column.nullable:
            parts.append("NOT NULL")
        ref = ddl.foreign.get((table.name, column.name))
        if ref:
            parts.append(f'REFERENCES "{ref[0]}" ("{ref[1]}")')
        comma = "," if i < len(columns) - 1 else ""
        comment = _one_line(ddl.columns.get((table.name, column.name), ""))
        lines.append(f"    {' '.join(parts)}{comma} -- {comment}")
    lines.append(")")
    return "\n".join(lines)


def _value(column: Column, value: object) -> object:
    if value is None:
        return None
    if column.kind == "money":
        return float(str(value))
    if column.kind in ("date", "timestamp"):
        return str(value)
    if column.kind == "bool":
        return 1 if value else 0
    return value


def export_sqlite(
    out: Path, sql_dir: Path, *, scale: float, seed: int = DEFAULT_SEED
) -> dict[str, int]:
    dataset = generate(GeneratorConfig(seed=seed, scale=scale))
    ddl = _read_ddl(sql_dir)
    out.parent.mkdir(parents=True, exist_ok=True)
    tmp = out.with_suffix(out.suffix + ".tmp")
    tmp.unlink(missing_ok=True)
    counts: dict[str, int] = {}
    with sqlite3.connect(tmp) as conn:
        conn.execute("PRAGMA foreign_keys = OFF")
        for table in dataset.tables:
            conn.execute(_create(table, ddl))
            placeholders = ", ".join("?" for _ in table.columns)
            rows = (
                tuple(_value(c, v) for c, v in zip(table.columns, row, strict=True))
                for row in table.iter_rows()
            )
            conn.executemany(f'INSERT INTO "{table.name}" VALUES ({placeholders})', rows)  # noqa: S608
            counts[table.name] = len(table)
        for name, table_name, columns in ddl.indexes:
            cols = ", ".join(f'"{c.strip()}"' for c in columns.split(","))
            conn.execute(f'CREATE INDEX "{name}" ON "{table_name}" ({cols})')
        conn.execute("ANALYZE")
    conn.close()
    tmp.replace(out)
    return counts


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="nexus-export-sqlite", description=__doc__)
    parser.add_argument("--out", type=Path, required=True, help="SQLite file to write")
    parser.add_argument("--sql-dir", type=Path, default=Path("/app/data/retail"))
    parser.add_argument("--scale", type=float, default=0.1, help="data volume (default 0.1)")
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    args = parser.parse_args(argv)
    counts = export_sqlite(args.out, args.sql_dir, scale=args.scale, seed=args.seed)
    sys.stdout.write(f"wrote {args.out} ({sum(counts.values())} rows in {len(counts)} tables)\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
