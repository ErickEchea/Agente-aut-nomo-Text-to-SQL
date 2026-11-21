"""Query-plan analysis and index suggestions (Phase 5, ADR-0013).

1. Ask the engine for its plan (never running the query): ``EXPLAIN (FORMAT JSON)`` on PostgreSQL,
   ``EXPLAIN FORMAT=JSON`` on MySQL, ``EXPLAIN QUERY PLAN`` on SQLite.
2. Find full scans of large tables and, from the query's AST, the columns those tables are filtered
   or joined on that no existing index starts with.
3. PostgreSQL with HypoPG: re-plan with each candidate as a *hypothetical* index (nothing is
   written) and keep the ones the planner would use, with the estimated cost before and after.
   MySQL and SQLite report the scan and the suggested index, without cost estimates.

Index DDL is built here from catalog identifiers and shown to the user; NEXUS never creates it.
"""

from __future__ import annotations

from collections.abc import Iterator
from dataclasses import dataclass, field
from typing import Literal

import sqlglot
from sqlglot import exp

from nexus.agent.catalog import SchemaCatalog
from nexus.datasources.dialects import Kind
from nexus.sql.executor import ExplainOutput, QueryExecutionError, ReadOnlyExecutor
from nexus.sql.validator import ValidatedSQL

LARGE_TABLE_ROWS = 5_000
MIN_IMPROVEMENT = 0.10
MAX_CANDIDATES = 4
Severity = Literal["high", "medium", "info"]


@dataclass(frozen=True, slots=True)
class PlanStep:
    depth: int
    operation: str
    table: str | None
    detail: str
    rows: float | None
    cost: float | None


@dataclass(frozen=True, slots=True)
class Finding:
    severity: Severity
    code: Literal["full_scan", "missing_index", "hypopg_unavailable", "no_issue"]
    table: str | None
    rows: int | None
    columns: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class IndexSuggestion:
    table: str
    columns: tuple[str, ...]
    ddl: str
    reason: Literal["filter", "join"]
    cost_before: float | None = None
    cost_after: float | None = None
    used_by_planner: bool | None = None

    @property
    def improvement(self) -> float | None:
        if self.cost_before is None or self.cost_after is None or self.cost_before <= 0:
            return None
        return max(0.0, 1 - self.cost_after / self.cost_before)


@dataclass(frozen=True, slots=True)
class OptimizationReport:
    engine: Kind
    supports_costs: bool
    total_cost: float | None
    plan: tuple[PlanStep, ...]
    findings: tuple[Finding, ...]
    suggestions: tuple[IndexSuggestion, ...]


# ---- columns the query filters or joins on -------------------------------------------------


@dataclass(slots=True)
class _Usage:
    filters: dict[str, set[str]] = field(default_factory=dict)  # table -> columns
    joins: dict[str, set[str]] = field(default_factory=dict)


def _alias_map(tree: exp.Expr, catalog: SchemaCatalog) -> dict[str, str]:
    aliases: dict[str, str] = {}
    for table in tree.find_all(exp.Table):
        if table.name in catalog.tables:
            aliases[(table.alias or table.name).lower()] = table.name
    return aliases


def _resolve(
    col: exp.Column, aliases: dict[str, str], catalog: SchemaCatalog, tables: set[str]
) -> str | None:
    if col.table:
        return aliases.get(col.table.lower())
    owners = [t for t in tables if any(c.name == col.name for c in catalog.tables[t].columns)]
    return owners[0] if len(owners) == 1 else None


def _comparisons(tree: exp.Expr) -> Iterator[exp.Expr]:
    for node in tree.walk():
        if isinstance(node, exp.EQ | exp.GT | exp.GTE | exp.LT | exp.LTE | exp.In | exp.Between):
            yield node


def column_usage(sql: str, dialect: str, catalog: SchemaCatalog) -> _Usage:
    tree = sqlglot.parse_one(sql, dialect=dialect)
    aliases = _alias_map(tree, catalog)
    tables = set(aliases.values())
    usage = _Usage()
    for node in _comparisons(tree):
        left = node.this if isinstance(node, exp.In | exp.Between) else node.args.get("this")
        right = None if isinstance(node, exp.In | exp.Between) else node.args.get("expression")
        if isinstance(left, exp.Column) and isinstance(right, exp.Column):
            for side in (left, right):
                owner = _resolve(side, aliases, catalog, tables)
                if owner:
                    usage.joins.setdefault(owner, set()).add(side.name)
            continue
        col = (
            left
            if isinstance(left, exp.Column)
            else right
            if isinstance(right, exp.Column)
            else None
        )
        if isinstance(col, exp.Column):
            owner = _resolve(col, aliases, catalog, tables)
            if owner:
                usage.filters.setdefault(owner, set()).add(col.name)
    return usage


# ---- plans per engine -----------------------------------------------------------------------


def _pg_steps(plan: object) -> tuple[list[PlanStep], float | None, list[str]]:
    """Flatten a PostgreSQL JSON plan; also return the tables read with a Seq Scan."""
    steps: list[PlanStep] = []
    scanned: list[str] = []
    root = (
        plan[0]["Plan"] if isinstance(plan, list) and plan and isinstance(plan[0], dict) else None
    )
    if not isinstance(root, dict):
        return steps, None, scanned

    def walk(node: dict[str, object], depth: int) -> None:
        operation = str(node.get("Node Type", "?"))
        table = node.get("Relation Name")
        detail = next(
            (
                str(node[k])
                for k in (
                    "Filter",
                    "Hash Cond",
                    "Index Cond",
                    "Join Filter",
                    "Merge Cond",
                    "Sort Key",
                )
                if k in node
            ),
            "",
        )
        steps.append(
            PlanStep(
                depth,
                operation,
                str(table) if table else None,
                detail[:200],
                _num(node.get("Plan Rows")),
                _num(node.get("Total Cost")),
            )
        )
        if operation == "Seq Scan" and table:
            scanned.append(str(table))
        children = node.get("Plans")
        for child in children if isinstance(children, list) else []:
            if isinstance(child, dict):
                walk(child, depth + 1)

    walk(root, 0)
    return steps, _num(root.get("Total Cost")), scanned


def _mysql_tables(node: object) -> Iterator[dict[str, object]]:
    if isinstance(node, dict):
        table = node.get("table")
        if isinstance(table, dict) and "table_name" in table:
            yield table
        for value in node.values():
            yield from _mysql_tables(value)
    elif isinstance(node, list):
        for item in node:
            yield from _mysql_tables(item)


def _mysql_steps(
    plan: object, aliases: dict[str, str]
) -> tuple[list[PlanStep], float | None, list[str]]:
    steps: list[PlanStep] = []
    scanned: list[str] = []
    block = plan.get("query_block") if isinstance(plan, dict) else None
    cost = None
    if isinstance(block, dict):
        info = block.get("cost_info")
        cost = _num(info.get("query_cost")) if isinstance(info, dict) else None
    for table in _mysql_tables(plan):
        name = str(table["table_name"])
        real = aliases.get(name.lower(), name)
        access = str(table.get("access_type", "?"))
        info = table.get("cost_info")
        steps.append(
            PlanStep(
                1,
                f"{access.upper()} access",
                real,
                str(table.get("attached_condition", ""))[:200],
                _num(table.get("rows_examined_per_scan")),
                _num(info.get("prefix_cost")) if isinstance(info, dict) else None,
            )
        )
        if access == "ALL":
            scanned.append(real)
    return steps, cost, scanned


def _sqlite_steps(
    rows: object, aliases: dict[str, str]
) -> tuple[list[PlanStep], float | None, list[str]]:
    steps: list[PlanStep] = []
    scanned: list[str] = []
    depth: dict[int, int] = {0: -1}
    for row in rows if isinstance(rows, list) else []:
        node_id, parent, detail = int(row[0]), int(row[1]), str(row[-1])
        depth[node_id] = depth.get(parent, -1) + 1
        words = detail.split()
        table = None
        if words and words[0] in ("SCAN", "SEARCH") and len(words) > 1:
            name = words[2] if words[1] == "TABLE" and len(words) > 2 else words[1]
            table = aliases.get(name.lower(), name)
            if words[0] == "SCAN" and "INDEX" not in words:
                scanned.append(table)
        steps.append(
            PlanStep(depth[node_id], words[0] if words else "?", table, detail[:200], None, None)
        )
    return steps, None, scanned


def _num(value: object) -> float | None:
    try:
        return float(str(value)) if value is not None else None
    except ValueError:
        return None


# ---- report ---------------------------------------------------------------------------------


def _quote(kind: Kind, name: str) -> str:
    if kind == "mysql":
        return "`" + name.replace("`", "``") + "`"
    return '"' + name.replace('"', '""') + '"'


def index_ddl(kind: Kind, schema: str, table: str, columns: tuple[str, ...]) -> str:
    qualified = (
        _quote(kind, table) if kind == "sqlite" else f"{_quote(kind, schema)}.{_quote(kind, table)}"
    )
    cols = ", ".join(_quote(kind, c) for c in columns)
    name = _quote(kind, f"{table}_{'_'.join(columns)}_idx")
    if kind == "postgresql":
        return f"CREATE INDEX ON {qualified} ({cols})"
    return f"CREATE INDEX {name} ON {qualified} ({cols})"


def _candidates(
    scanned: list[str],
    usage: _Usage,
    indexes: set[tuple[str, str]],
    rows: dict[str, int],
    catalog: SchemaCatalog,
) -> list[tuple[str, str, Literal["filter", "join"]]]:
    out: list[tuple[str, str, Literal["filter", "join"]]] = []
    for table in dict.fromkeys(scanned):
        if table not in catalog.tables or rows.get(table, 0) < LARGE_TABLE_ROWS:
            continue
        for reason, columns in (
            ("filter", usage.filters.get(table, set())),
            ("join", usage.joins.get(table, set())),
        ):
            for column in sorted(columns):
                if (table, column) not in indexes and all(
                    (table, column) != (t, c) for t, c, _ in out
                ):
                    out.append((table, column, reason))  # type: ignore[arg-type]
    return out[:MAX_CANDIDATES]


def _uses_hypothetical(plan: object) -> bool:
    text = str(plan)
    return "<" in text and "btree" in text


async def analyze(
    executor: ReadOnlyExecutor,
    query: ValidatedSQL,
    *,
    kind: Kind,
    dialect: str,
    catalog: SchemaCatalog,
    rows: dict[str, int],
    indexes: set[tuple[str, str]],
) -> OptimizationReport:
    explained: ExplainOutput = await executor.explain(query)
    aliases = _alias_map(sqlglot.parse_one(query.sql, dialect=dialect), catalog)
    if explained.format == "postgres_json":
        steps, total, scanned = _pg_steps(explained.plan)
    elif explained.format == "mysql_json":
        steps, total, scanned = _mysql_steps(explained.plan, aliases)
    else:
        steps, total, scanned = _sqlite_steps(explained.plan, aliases)

    usage = column_usage(query.sql, dialect, catalog)
    findings: list[Finding] = []
    for table in dict.fromkeys(scanned):
        count = rows.get(table)
        large = count is not None and count >= LARGE_TABLE_ROWS
        findings.append(Finding("medium" if large else "info", "full_scan", table, count))

    suggestions: list[IndexSuggestion] = []
    hypothetical_ok = kind == "postgresql"
    for table, column, reason in _candidates(scanned, usage, indexes, rows, catalog):
        ddl = index_ddl(kind, catalog.schema, table, (column,))
        if kind != "postgresql":
            suggestions.append(IndexSuggestion(table, (column,), ddl, reason))
            continue
        if not hypothetical_ok:
            suggestions.append(IndexSuggestion(table, (column,), ddl, reason, total))
            continue
        try:
            after_plan = await executor.explain_with_hypothetical_index(query, ddl)
        except QueryExecutionError:
            hypothetical_ok = False  # HypoPG not installed for this source
            findings.append(Finding("info", "hypopg_unavailable", None, None))
            suggestions.append(IndexSuggestion(table, (column,), ddl, reason, total))
            continue
        _, after, _ = _pg_steps(after_plan)
        suggestion = IndexSuggestion(
            table, (column,), ddl, reason, total, after, _uses_hypothetical(after_plan)
        )
        improvement = suggestion.improvement
        if (
            suggestion.used_by_planner
            and improvement is not None
            and improvement >= MIN_IMPROVEMENT
        ):
            suggestions.append(suggestion)

    findings.extend(
        Finding("high", "missing_index", s.table, rows.get(s.table), s.columns) for s in suggestions
    )
    if not findings:
        findings.append(Finding("info", "no_issue", None, None))
    suggestions.sort(key=lambda s: -(s.improvement or 0))
    return OptimizationReport(
        engine=kind,
        supports_costs=kind != "sqlite",
        total_cost=total,
        plan=tuple(steps),
        findings=tuple(findings),
        suggestions=tuple(suggestions),
    )
