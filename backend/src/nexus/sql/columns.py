"""Unknown-column hints: where the database looked for a column it rejected, and where it really is.

Engines report an unknown column without saying where the query looked for it (PostgreSQL:
``column "region_id" does not exist``). A model repairing its SQL from that message alone tends to
repeat the same query. Resolving each column reference scope by scope, against the catalog and the
query's own CTEs and subqueries, gives the repair step the missing facts: the source it was looked
up in, that source's real columns, a CTE hiding a real table of the same name, and the tables that
do have the column.
"""

from __future__ import annotations

import re
from dataclasses import dataclass

import sqlglot
from sqlglot import exp
from sqlglot.errors import SqlglotError
from sqlglot.optimizer.scope import Scope, traverse_scope, walk_in_scope

from nexus.agent.catalog import SchemaCatalog


@dataclass(frozen=True, slots=True)
class SearchedSource:
    """A FROM item the reference could have come from, and the columns it really provides."""

    name: str  # catalog table name, or the CTE / subquery name inside the query
    columns: tuple[str, ...]
    kind: str  # "table" | "cte" | "subquery"


@dataclass(frozen=True, slots=True)
class UnknownColumn:
    name: str
    searched: tuple[SearchedSource, ...]
    owners: tuple[str, ...]  # catalog tables that do have a column with this name


type Candidate = tuple[str, exp.Expr, exp.Expr | Scope]  # FROM alias, FROM node, its source


def _source(candidate: Candidate, catalog: SchemaCatalog) -> SearchedSource | None:
    """What a selected source provides, or None when it cannot be told (then anything goes)."""
    alias, node, source = candidate
    if isinstance(source, Scope):
        if not isinstance(source.expression, exp.Query):
            return None
        names = source.expression.named_selects
        if "*" in names:
            return None
        # A CTE is named by its definition (FROM regiones AS r → regiones); a subquery by its alias.
        name = node.name if isinstance(node, exp.Table) else alias
        return SearchedSource(name, tuple(names), "cte" if source.is_cte else "subquery")
    if isinstance(source, exp.Table) and source.name in catalog.tables:
        columns = tuple(c.name for c in catalog.tables[source.name].columns)
        return SearchedSource(source.name, columns, "table")
    return None


def _candidates(col: exp.Column, scope: Scope) -> list[Candidate] | None:
    """FROM items a reference may resolve to: its qualifier's, or every one of the innermost scope
    that has any (correlated references reach outer scopes). None when it cannot be told."""
    current: Scope | None = scope
    while current is not None:
        selected = current.selected_sources
        if col.table:
            if col.table in selected:
                return [(col.table, *selected[col.table])]
        elif selected:
            return [(alias, node, source) for alias, (node, source) in selected.items()]
        current = current.parent
    return None


def unknown_columns(sql: str, dialect: str, catalog: SchemaCatalog) -> list[UnknownColumn]:
    """Column references that no FROM item in scope provides."""
    try:
        tree = sqlglot.parse_one(sql, dialect=dialect)
        scopes = traverse_scope(tree)
    except SqlglotError:
        return []
    found: dict[str, UnknownColumn] = {}
    for scope in scopes:
        # Explicit select aliases (ORDER BY total); a bare column's output name is not one.
        selects = scope.expression.selects if isinstance(scope.expression, exp.Select) else []
        own_aliases = {s.alias.lower() for s in selects if isinstance(s, exp.Alias)}
        for col in scope.columns:
            name = col.name.lower()
            if not name or name in found or (not col.table and name in own_aliases):
                continue
            candidates = _candidates(col, scope)
            if not candidates:
                continue
            sources = [_source(candidate, catalog) for candidate in candidates]
            if any(s is None or name in {c.lower() for c in s.columns} for s in sources):
                continue
            owners = tuple(
                sorted(
                    t.name
                    for t in catalog.tables.values()
                    if any(c.name.lower() == name for c in t.columns)
                )
            )
            searched = tuple(dict.fromkeys(s for s in sources if s is not None))
            found[name] = UnknownColumn(col.name, searched, owners)
    return list(found.values())


def _describe(source: SearchedSource, catalog: SchemaCatalog) -> str:
    columns = ", ".join(source.columns)
    if source.kind == "table":
        return f"{catalog.schema}.{source.name} (sus columnas son: {columns})"
    label = "el CTE" if source.kind == "cte" else "la subconsulta"
    defined = "definido" if source.kind == "cte" else "definida"
    text = f"{label} «{source.name}» {defined} en la consulta (solo devuelve: {columns})"
    if source.kind == "cte" and source.name in catalog.tables:
        text += f"; ese nombre oculta la tabla {catalog.schema}.{source.name}"
    return text


def _unknown_column_lines(
    sql: str, dialect: str, catalog: SchemaCatalog, error_message: str
) -> list[str]:
    lines: list[str] = []
    for unknown in unknown_columns(sql, dialect, catalog):
        if not re.search(rf"\b{re.escape(unknown.name)}\b", error_message, re.IGNORECASE):
            continue
        lines.extend(
            f"- La columna «{unknown.name}» no existe en {_describe(source, catalog)}."
            for source in unknown.searched
        )
        if unknown.owners:
            owners = ", ".join(f"{catalog.schema}.{t}" for t in unknown.owners)
            lines.append(f"- «{unknown.name}» sí existe en: {owners}.")
        else:
            lines.append(f"- «{unknown.name}» no existe en ninguna tabla del esquema.")
    return lines


# ---- comparisons between columns of different types -------------------------------------------

_FAMILIES = {
    "smallint": "number", "integer": "number", "int": "number", "bigint": "number",
    "numeric": "number", "decimal": "number", "real": "number", "double precision": "number",
    "text": "text", "character varying": "text", "varchar": "text", "character": "text",
    "date": "time", "timestamp": "time", "timestamp without time zone": "time",
    "timestamp with time zone": "time", "boolean": "boolean",
}  # fmt: skip
_COMPARISONS = (exp.EQ, exp.NEQ, exp.GT, exp.GTE, exp.LT, exp.LTE)


def _base_type(data_type: str) -> str:
    return data_type.split("(", maxsplit=1)[0].strip().lower()


@dataclass(frozen=True, slots=True)
class TypedColumn:
    reference: str  # as written in the query: pr.provincia
    data_type: str  # catalog type of the column it comes from
    origin: str  # schema.table.column it comes from
    via: SearchedSource | None  # the CTE or subquery it was read through, if any


def _typed(
    col: exp.Column, scope: Scope, catalog: SchemaCatalog, depth: int = 0
) -> tuple[str, str] | None:
    """(catalog type, origin) of a reference, following plain projections of CTEs/subqueries."""
    candidates = _candidates(col, scope) if depth < 8 else None
    if not candidates:
        return None
    name = col.name.lower()
    hits: list[tuple[str, str]] = []
    for _, _, source in candidates:
        if isinstance(source, Scope) and isinstance(source.expression, exp.Select):
            for projection in source.expression.selects:
                inner = projection.unalias()
                if projection.alias_or_name.lower() == name and isinstance(inner, exp.Column):
                    resolved = _typed(inner, source, catalog, depth + 1)
                    hits.extend([resolved] if resolved else [])
        elif isinstance(source, exp.Table) and source.name in catalog.tables:
            hits.extend(
                (c.data_type, f"{catalog.schema}.{source.name}.{c.name}")
                for c in catalog.tables[source.name].columns
                if c.name.lower() == name
            )
    return hits[0] if len(hits) == 1 else None


def _typed_column(col: exp.Column, scope: Scope, catalog: SchemaCatalog) -> TypedColumn | None:
    resolved = _typed(col, scope, catalog)
    if resolved is None:
        return None
    candidates = _candidates(col, scope) or []
    via = None
    if col.table and len(candidates) == 1 and isinstance(candidates[0][2], Scope):
        via = _source(candidates[0], catalog)
    return TypedColumn(col.sql(), resolved[0], resolved[1], via)


def type_mismatches(
    sql: str, dialect: str, catalog: SchemaCatalog
) -> list[tuple[TypedColumn, TypedColumn]]:
    """Column-to-column comparisons whose catalog types belong to different families."""
    try:
        tree = sqlglot.parse_one(sql, dialect=dialect)
        scopes = traverse_scope(tree)
    except SqlglotError:
        return []
    found: list[tuple[TypedColumn, TypedColumn]] = []
    for scope in scopes:
        for node in walk_in_scope(scope.expression):
            if not isinstance(node, _COMPARISONS):
                continue
            left, right = node.this, node.expression
            if not (isinstance(left, exp.Column) and isinstance(right, exp.Column)):
                continue
            a, b = _typed_column(left, scope, catalog), _typed_column(right, scope, catalog)
            if a is None or b is None:
                continue
            family_a = _FAMILIES.get(_base_type(a.data_type))
            family_b = _FAMILIES.get(_base_type(b.data_type))
            if family_a and family_b and family_a != family_b:
                found.append((a, b))
    return found


def _type_mismatch_lines(
    sql: str, dialect: str, catalog: SchemaCatalog, error_message: str
) -> list[str]:
    lines: list[str] = []
    message = error_message.lower()
    for a, b in type_mismatches(sql, dialect, catalog):
        if _base_type(a.data_type) not in message or _base_type(b.data_type) not in message:
            continue
        lines.append(
            f"- Se comparan tipos distintos: {a.reference} ({a.data_type}, de {a.origin}) con "
            f"{b.reference} ({b.data_type}, de {b.origin})."
        )
        for side in (a, b):
            if side.via is not None:
                alias = side.reference.split(".")[0]
                lines.append(f"- «{alias}» es {_describe(side.via, catalog)}.")
    return list(dict.fromkeys(lines))


def catalog_hint(sql: str, dialect: str, catalog: SchemaCatalog, error_message: str) -> str | None:
    """A Spanish hint for the repair prompt about the columns the engine's error is about: unknown
    columns and comparisons between incompatible types. None when the error names neither."""
    lines = _unknown_column_lines(sql, dialect, catalog, error_message)
    lines += _type_mismatch_lines(sql, dialect, catalog, error_message)
    if not lines:
        return None
    return "Según el catálogo del esquema:\n" + "\n".join(lines)
