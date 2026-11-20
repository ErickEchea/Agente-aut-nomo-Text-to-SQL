"""Optional masking of configured PII columns in query results, before they leave the backend.

Output columns are traced through the SQL AST, so aliases (``SELECT email AS contacto``) and
expressions (``lower(email)``) are masked too. Pure counts (``count(email)``) are not personal
data and are left alone. ``SELECT *`` over a PII table masks by output column name.
"""

from __future__ import annotations

from collections.abc import Iterable

import sqlglot
from sqlglot import exp

from nexus.sql.executor import JsonScalar

MASK = "•"


def mask_value(value: JsonScalar) -> JsonScalar:
    if value is None:
        return None
    text = str(value)
    if len(text) <= 4:
        return MASK * len(text)
    return MASK * (len(text) - 2) + text[-2:]


def _only_counted(node: exp.Expression) -> bool:
    """True if every PII reference sits inside COUNT(...)."""
    return all(col.find_ancestor(exp.Count) is not None for col in node.find_all(exp.Column))


class PiiMasker:
    def __init__(self, pii_columns: Iterable[str]) -> None:
        """``pii_columns`` like ``["clientes.cedula", "clientes.email"]``."""
        self._pairs = {tuple(item.lower().split(".", 1)) for item in pii_columns if "." in item}
        self._names = {column for _, column in self._pairs}
        self._tables = {table for table, _ in self._pairs}

    @property
    def enabled(self) -> bool:
        return bool(self._pairs)

    @staticmethod
    def _derives_from(node: exp.Expression, names: set[str]) -> bool:
        refs = [c for c in node.find_all(exp.Column) if c.name.lower() in names]
        return bool(refs) and not _only_counted(node)

    def _sensitive_names(self, tree: exp.Expr) -> set[str]:
        """PII column names plus every alias derived from them anywhere (CTEs, subqueries)."""
        names = set(self._names)
        changed = True
        while changed:
            changed = False
            for alias in tree.find_all(exp.Alias):
                name = alias.alias.lower()
                if name not in names and self._derives_from(alias.this, names):
                    names.add(name)
                    changed = True
        return names

    def sensitive_columns(self, sql: str, columns: tuple[str, ...]) -> set[int]:
        if not self.enabled:
            return set()
        try:
            tree = sqlglot.parse_one(sql, dialect="postgres")
        except sqlglot.errors.ParseError:
            return set(range(len(columns)))  # cannot reason about it: mask everything
        names = self._sensitive_names(tree)
        indexes = {i for i, name in enumerate(columns) if name.lower() in names}
        select = tree if isinstance(tree, exp.Select) else tree.find(exp.Select)
        if select is None:
            return indexes
        projections = select.expressions
        if any(isinstance(p, exp.Star) for p in projections):
            return indexes
        for i, projection in enumerate(projections[: len(columns)]):
            if self._derives_from(projection, names):
                indexes.add(i)
        return indexes

    def mask(
        self, sql: str, columns: tuple[str, ...], rows: list[tuple[JsonScalar, ...]]
    ) -> tuple[list[tuple[JsonScalar, ...]], tuple[str, ...]]:
        """Return (masked rows, names of masked columns)."""
        sensitive = self.sensitive_columns(sql, columns)
        if not sensitive:
            return rows, ()
        masked = [
            tuple(mask_value(v) if i in sensitive else v for i, v in enumerate(row)) for row in rows
        ]
        return masked, tuple(columns[i] for i in sorted(sensitive))
