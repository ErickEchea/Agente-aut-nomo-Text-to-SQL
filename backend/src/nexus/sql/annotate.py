"""Clause-by-clause explanation of a validated query, linked to character spans (Phase 5).

Deterministic: the query is segmented with the dialect's tokenizer at clause keywords of the main
query and of each CTE body (subqueries inside predicates stay within their clause), re-flowed one
clause per line for display, and every clause is described from the AST, the catalog's comments
and the glossary rules it satisfies. No model is involved, so the explanation cannot invent tables,
filters or rules that are not in the SQL.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Literal

import sqlglot
from sqlglot import Token, TokenType, exp
from sqlglot.dialects.dialect import Dialect

from nexus.agent.catalog import SchemaCatalog
from nexus.agent.glossary import Glossary

ClauseKind = Literal[
    "cte", "select", "from", "join", "where", "group_by", "having", "order_by", "limit", "set_op"
]
Locale = Literal["es", "en"]

# Words that end with a period without ending the sentence ("p. ej.", "e.g.", "aprox.").
_ABBREVIATIONS = frozenset(
    {"p", "ej", "e.g", "i.e", "etc", "aprox", "approx", "vs", "núm", "no", "nro", "sr", "sra", "dr"}
)


def first_sentence(text: str) -> str:
    """The first sentence of a comment: a period followed by whitespace that is not an abbreviation.

    Decimal points ("1.5 L") and abbreviations ("p. ej. QUI-01") do not end the sentence.
    """
    for index, char in enumerate(text):
        if char != "." or index + 1 >= len(text) or not text[index + 1].isspace():
            continue
        word = text[:index].rsplit(None, 1)[-1].lower() if text[:index].strip() else ""
        if word.lstrip("(") not in _ABBREVIATIONS:
            return text[: index + 1].strip()
    return text.strip()


_STARTS: dict[TokenType, ClauseKind] = {
    TokenType.SELECT: "select",
    TokenType.FROM: "from",
    TokenType.JOIN: "join",
    TokenType.WHERE: "where",
    TokenType.GROUP_BY: "group_by",
    TokenType.HAVING: "having",
    TokenType.ORDER_BY: "order_by",
    TokenType.LIMIT: "limit",
    TokenType.UNION: "set_op",
    TokenType.INTERSECT: "set_op",
    TokenType.EXCEPT: "set_op",
}
_JOIN_MODIFIERS = {
    TokenType.LEFT, TokenType.RIGHT, TokenType.INNER, TokenType.OUTER, TokenType.FULL,
    TokenType.CROSS, TokenType.NATURAL, TokenType.SEMI, TokenType.ANTI,
}  # fmt: skip

_TEXT: dict[Locale, dict[str, str]] = {
    "es": {
        "cte": "Subconsulta «{name}»",
        "cte_detail": "Calcula un resultado intermedio a partir de {tables}{agg}.",
        "cte_agg": ", agregando por {keys}",
        "select": "Columnas del resultado",
        "from": "Tabla principal",
        "join": "Unión ({kind})",
        "where": "Filtros",
        "group_by": "Agrupación",
        "having": "Filtro sobre grupos",
        "order_by": "Orden",
        "limit": "Límite de filas",
        "set_op": "Combinación de resultados",
        "reads": "Lee {table}{comment}.",
        "joins": "Une {table}{comment} cuando {cond}.",
        "group": "Una fila por cada combinación de: {keys}.",
        "order": "{expr} {direction}",
        "asc": "ascendente",
        "desc": "descendente",
        "limit_n": "Devuelve como máximo {n} filas.",
        "limit_added": " NEXUS agregó este límite por seguridad.",
        "set_detail": "Combina los resultados de varias consultas ({op}).",
        "sum": "suma de {x}",
        "count": "conteo de {x}",
        "count_star": "número de filas",
        "count_distinct": "número de {x} distintos",
        "avg": "promedio de {x}",
        "min": "mínimo de {x}",
        "max": "máximo de {x}",
        "calc": "cálculo: {x}",
        "as": "«{alias}» = {what}",
        "eq_text": "{col} es «{value}»",
        "eq": "{left} = {right}",
        "neq": "{left} distinto de {right}",
        "gte": "{col} desde {value}",
        "gt": "{col} posterior/mayor a {value}",
        "lt": "{col} antes de {value} (sin incluirlo)",
        "lte": "{col} hasta {value}",
        "in": "{col} está entre: {values}",
        "like": "{col} coincide con «{pattern}»",
        "null": "{col} está vacío",
        "not_null": "{col} tiene valor",
        "between": "{col} entre {low} y {high}",
        "not_exists": "Excluye las filas que tienen un registro relacionado en {tables} ({cond}).",
        "exists": "Solo filas con un registro relacionado en {tables} ({cond}).",
        "rule": "Regla del glosario «{term}»: {definition}",
        "join_inner": "solo coincidencias",
        "join_left": "conserva todas las filas de la izquierda",
        "join_right": "conserva todas las filas de la derecha",
        "join_full": "conserva todas las filas",
        "join_cross": "todas las combinaciones",
    },
    "en": {
        "cte": "Subquery “{name}”",
        "cte_detail": "Computes an intermediate result from {tables}{agg}.",
        "cte_agg": ", aggregated by {keys}",
        "select": "Result columns",
        "from": "Main table",
        "join": "Join ({kind})",
        "where": "Filters",
        "group_by": "Grouping",
        "having": "Group filter",
        "order_by": "Ordering",
        "limit": "Row limit",
        "set_op": "Combined results",
        "reads": "Reads {table}{comment}.",
        "joins": "Joins {table}{comment} when {cond}.",
        "group": "One row per combination of: {keys}.",
        "order": "{expr} {direction}",
        "asc": "ascending",
        "desc": "descending",
        "limit_n": "Returns at most {n} rows.",
        "limit_added": " NEXUS added this limit for safety.",
        "set_detail": "Combines the results of several queries ({op}).",
        "sum": "sum of {x}",
        "count": "count of {x}",
        "count_star": "number of rows",
        "count_distinct": "number of distinct {x}",
        "avg": "average of {x}",
        "min": "minimum of {x}",
        "max": "maximum of {x}",
        "calc": "computed: {x}",
        "as": "“{alias}” = {what}",
        "eq_text": "{col} is “{value}”",
        "eq": "{left} = {right}",
        "neq": "{left} different from {right}",
        "gte": "{col} from {value}",
        "gt": "{col} after/greater than {value}",
        "lt": "{col} before {value} (exclusive)",
        "lte": "{col} up to {value}",
        "in": "{col} is one of: {values}",
        "like": "{col} matches “{pattern}”",
        "null": "{col} is empty",
        "not_null": "{col} has a value",
        "between": "{col} between {low} and {high}",
        "not_exists": "Excludes rows that have a related record in {tables} ({cond}).",
        "exists": "Only rows with a related record in {tables} ({cond}).",
        "rule": "Glossary rule “{term}”: {definition}",
        "join_inner": "matches only",
        "join_left": "keeps every left row",
        "join_right": "keeps every right row",
        "join_full": "keeps every row",
        "join_cross": "every combination",
    },
}


@dataclass(frozen=True, slots=True)
class Clause:
    kind: ClauseKind
    scope: str  # "" for the main query, else the CTE name
    start: int  # span in AnnotatedSQL.sql (end exclusive)
    end: int
    title: str
    details: tuple[str, ...]
    rules: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class AnnotatedSQL:
    sql: str  # display form: one clause per line, CTE bodies indented
    clauses: tuple[Clause, ...]


@dataclass(slots=True)
class _Break:
    pos: int
    kind: ClauseKind
    scope: str
    indent: int


@dataclass(slots=True)
class _Scope:
    name: str
    node: exp.Expr | None
    joins_seen: int = 0
    aliases: dict[str, str] = field(default_factory=dict)


# ---- segmentation ----------------------------------------------------------------------------


@dataclass(slots=True)
class _Walker:
    """Tracks parentheses: a CTE body ("<name> AS (") opens a scope whose clauses are broken out;
    any other parenthesis (subquery, function call) keeps its contents inside the current clause."""

    tokens: list[Token]
    breaks: list[_Break] = field(default_factory=list)
    stack: list[str | None] = field(default_factory=lambda: [""])
    in_with: bool = False
    with_start: int = 0

    def open_paren(self, i: int) -> None:
        prev = self.tokens[i - 1] if i > 0 else None
        prev2 = self.tokens[i - 2] if i > 1 else None
        opens_cte = (
            self.in_with
            and self.stack[-1] == ""
            and prev is not None
            and prev.token_type == TokenType.ALIAS
            and prev2 is not None
        )
        self.stack.append(prev2.text.strip('"`') if opens_cte and prev2 else None)

    def cte_name(self, i: int) -> bool:
        tok = self.tokens[i]
        nxt = self.tokens[i + 1] if i + 1 < len(self.tokens) else None
        if nxt is None or nxt.token_type != TokenType.ALIAS:
            return False
        # The first CTE line carries the WITH keyword.
        start = self.with_start if not self.breaks else tok.start
        self.breaks.append(_Break(start, "cte", tok.text.strip('"`'), 0))
        return True

    def clause(self, i: int, kind: ClauseKind) -> None:
        top = self.stack[-1] or ""
        if top == "" and kind == "select":
            self.in_with = False
        start = self.tokens[i].start
        if kind == "join":
            j = i - 1
            while j >= 0 and self.tokens[j].token_type in _JOIN_MODIFIERS:
                start = self.tokens[j].start
                j -= 1
        self.breaks.append(_Break(start, kind, top, 2 if top else 0))

    def step(self, i: int) -> None:
        kind = self.tokens[i].token_type
        if kind == TokenType.L_PAREN:
            self.open_paren(i)
            return
        if kind == TokenType.R_PAREN:
            if len(self.stack) > 1:
                self.stack.pop()
            return
        top = self.stack[-1]
        if top is None:
            return
        if kind == TokenType.WITH and top == "":
            self.in_with = True
            self.with_start = self.tokens[i].start
            return
        is_name = kind in (TokenType.VAR, TokenType.IDENTIFIER)
        if self.in_with and top == "" and is_name and self.cte_name(i):
            return
        clause = _STARTS.get(kind)
        if clause is not None:
            self.clause(i, clause)


def _breaks(sql: str, dialect: str) -> list[_Break]:
    walker = _Walker(list(Dialect.get_or_raise(dialect).tokenize(sql)))
    for i in range(len(walker.tokens)):
        walker.step(i)
    if not walker.breaks:
        return [_Break(0, "select", "", 0)]
    walker.breaks[0].pos = 0  # any leading text belongs to the first clause
    return walker.breaks


# ---- descriptions ----------------------------------------------------------------------------


def _subquery_condition(sub: exp.Expr) -> str:
    where = sub.args.get("where") if isinstance(sub, exp.Select) else None
    return where.this.sql() if where is not None else ""


class _Describer:
    def __init__(
        self, catalog: SchemaCatalog, glossary: Glossary, question: str, locale: Locale
    ) -> None:
        self.catalog = catalog
        self.t = _TEXT[locale]
        self.rule_terms = [t for t in glossary.terms_in(question) if t.requires is not None]

    # names

    def _table_comment(self, table: str) -> str:
        info = self.catalog.tables.get(table) or self.catalog.tables.get(table.lower())
        return f" ({info.comment.rstrip('.')})" if info and info.comment else ""

    def column(self, node: exp.Column, scope: _Scope) -> str:
        table = scope.aliases.get(node.table.lower(), node.table) if node.table else ""
        qualified = f"{table}.{node.name}" if table else node.name
        info = self.catalog.tables.get(table)
        col = next((c for c in info.columns if c.name == node.name), None) if info else None
        if col is not None and col.comment:
            short = first_sentence(col.comment).split(";")[0].rstrip(".")
            if len(short) > 60:
                short = short[:60].rsplit(" ", 1)[0].rstrip(",") + "…"
            return f"{qualified} ({short[:1].lower()}{short[1:]})"
        return qualified

    def expr(self, node: exp.Expr, scope: _Scope) -> str:
        t = self.t
        if isinstance(node, exp.Column):
            return self.column(node, scope)
        if isinstance(node, exp.Count):
            return self._count(node, scope)
        for cls, key in ((exp.Sum, "sum"), (exp.Avg, "avg"), (exp.Min, "min"), (exp.Max, "max")):
            if isinstance(node, cls):
                return t[key].format(x=self.expr(node.this, scope))
        if isinstance(node, exp.Literal):
            return node.sql()
        return t["calc"].format(x=node.sql())

    def _count(self, node: exp.Count, scope: _Scope) -> str:
        target = node.this
        if isinstance(target, exp.Distinct):
            inner = target.expressions[0] if target.expressions else target
            return self.t["count_distinct"].format(x=self.expr(inner, scope))
        if target is None or isinstance(target, exp.Star):
            return self.t["count_star"]
        return self.t["count"].format(x=self.expr(target, scope))

    @staticmethod
    def value(node: exp.Expr) -> str:
        if isinstance(node, exp.Cast) and isinstance(node.this, exp.Literal):
            return node.this.name
        if isinstance(node, exp.Literal):
            return node.name if node.is_string else node.sql()
        return node.sql()

    @staticmethod
    def tables_of(node: exp.Expr) -> list[str]:
        return sorted({tbl.name for tbl in node.find_all(exp.Table)})

    # predicates

    def predicate(self, node: exp.Expr, scope: _Scope) -> str:
        if isinstance(node, exp.Paren):
            return self.predicate(node.this, scope)
        if isinstance(node, exp.Not) and isinstance(node.this, exp.Exists):
            return self._exists(node.this.this, "not_exists")
        if isinstance(node, exp.Exists):
            return self._exists(node.this, "exists")
        if isinstance(node, exp.Binary) and isinstance(node.left, exp.Column):
            return self._binary(node, scope)
        return self._other(node, scope)

    def _exists(self, sub: exp.Expr, key: str) -> str:
        tables = ", ".join(self.tables_of(sub))
        return self.t[key].format(tables=tables, cond=_subquery_condition(sub))

    def _binary(self, node: exp.Binary, scope: _Scope) -> str:
        t = self.t
        col = self.column(node.left, scope)  # type: ignore[arg-type]
        right = node.right
        if isinstance(node, exp.Is):  # IS NULL is a binary node in sqlglot
            return t["null"].format(col=col)
        if isinstance(node, exp.EQ):
            if isinstance(right, exp.Literal) and right.is_string:
                return t["eq_text"].format(col=col, value=right.name)
            other = (
                self.column(right, scope) if isinstance(right, exp.Column) else self.value(right)
            )
            return t["eq"].format(left=col, right=other)
        keys = ((exp.GTE, "gte"), (exp.GT, "gt"), (exp.LT, "lt"), (exp.LTE, "lte"))
        for cls, key in keys:
            if isinstance(node, cls):
                return t[key].format(col=col, value=self.value(right))
        if isinstance(node, exp.NEQ):
            return t["neq"].format(left=col, right=self.value(right))
        if isinstance(node, exp.Like):
            return t["like"].format(col=col, pattern=self.value(right))
        return node.sql()

    def _other(self, node: exp.Expr, scope: _Scope) -> str:
        t = self.t
        target = node.this if isinstance(node, exp.Not) and isinstance(node.this, exp.Is) else node
        column = target.this if isinstance(target, exp.In | exp.Is | exp.Between) else None
        if not isinstance(column, exp.Column):
            return node.sql()
        col = self.column(column, scope)
        if isinstance(target, exp.In):
            values = ", ".join(self.value(v) for v in target.expressions) or target.sql()
            return t["in"].format(col=col, values=values)
        if isinstance(target, exp.Between):
            low, high = self.value(target.args["low"]), self.value(target.args["high"])
            return t["between"].format(col=col, low=low, high=high)
        return t["not_null" if target is not node else "null"].format(col=col)

    def rules_for(self, node: exp.Expr) -> list[str]:
        """Glossary rules (of terms in the question) that this clause implements."""
        literals = {lit.name.lower() for lit in node.find_all(exp.Literal) if lit.is_string}
        excluded = {
            tbl.name.lower()
            for not_ in node.find_all(exp.Not)
            if isinstance(not_.this, exp.Exists)
            for tbl in not_.this.find_all(exp.Table)
        }
        out = []
        for term in self.rule_terms:
            rule = term.requires
            if rule is None:
                continue
            by_literal = any(lit.lower() in literals for lit in rule.literals)
            if by_literal or any(tbl.lower() in excluded for tbl in rule.tables):
                definition = first_sentence(term.definition).rstrip(".") + "."
                out.append(self.t["rule"].format(term=term.term, definition=definition))
        return out

    # clauses

    def describe(
        self, kind: ClauseKind, scope: _Scope, limit_added: bool, root: exp.Expr
    ) -> tuple[str, list[str], list[str]]:
        node = scope.node
        if kind == "set_op" and isinstance(root, exp.SetOperation):
            op = type(root).__name__.upper()
            return self.t["set_op"], [self.t["set_detail"].format(op=op)], []
        if kind == "limit" and isinstance(root, exp.SetOperation) and not scope.name:
            return self._limit(root, limit_added)  # LIMIT applies to the whole set operation
        if not isinstance(node, exp.Select):
            return self.t.get(kind, kind), [], []
        handlers = {
            "cte": self._cte,
            "select": self._select,
            "from": self._from,
            "join": self._join,
            "where": self._where,
            "group_by": self._group,
            "having": self._having,
            "order_by": self._order,
        }
        if kind == "limit":
            return self._limit(node, limit_added)
        handler = handlers.get(kind)
        if handler is None:
            return self.t.get(kind, kind), [], []
        return handler(node, scope)

    def _cte(self, node: exp.Select, scope: _Scope) -> tuple[str, list[str], list[str]]:
        group = node.args.get("group")
        agg = ""
        if group is not None:
            keys = ", ".join(self.expr(e, scope) for e in group.expressions)
            agg = self.t["cte_agg"].format(keys=keys)
        tables = ", ".join(self.tables_of(node)) or "—"
        detail = self.t["cte_detail"].format(tables=tables, agg=agg)
        return self.t["cte"].format(name=scope.name), [detail], []

    def _select(self, node: exp.Select, scope: _Scope) -> tuple[str, list[str], list[str]]:
        lines = []
        for projection in node.expressions:
            if isinstance(projection, exp.Alias):
                what = self.expr(projection.this, scope)
                lines.append(self.t["as"].format(alias=projection.alias, what=what))
            else:
                lines.append(self.expr(projection, scope))
        return self.t["select"], lines, []

    def _from(self, node: exp.Select, scope: _Scope) -> tuple[str, list[str], list[str]]:
        source = node.args.get("from_") or node.args.get("from")  # sqlglot >= 30 uses from_
        table = source.this if source is not None else None
        if isinstance(table, exp.Table):
            line = self.t["reads"].format(table=table.name, comment=self._table_comment(table.name))
            return self.t["from"], [line], []
        return self.t["from"], [source.sql() if source is not None else ""], []

    def _join(self, node: exp.Select, scope: _Scope) -> tuple[str, list[str], list[str]]:
        joins = node.args.get("joins") or []
        join = joins[scope.joins_seen] if scope.joins_seen < len(joins) else None
        scope.joins_seen += 1
        if join is None:
            return self.t["join"].format(kind=""), [], []
        side = (join.side or join.kind or "inner").lower()
        label = self.t.get(f"join_{side}", side)
        target = join.this
        name = target.name if isinstance(target, exp.Table) else target.sql()
        cond_node = join.args.get("on")
        cond = self.predicate(cond_node, scope) if cond_node is not None else "—"
        line = self.t["joins"].format(table=name, comment=self._table_comment(name), cond=cond)
        return self.t["join"].format(kind=label), [line], []

    def _where(self, node: exp.Select, scope: _Scope) -> tuple[str, list[str], list[str]]:
        where = node.args.get("where")
        if where is None:
            return self.t["where"], [], []
        parts = list(where.this.flatten()) if isinstance(where.this, exp.And) else [where.this]
        return self.t["where"], [self.predicate(p, scope) for p in parts], self.rules_for(where)

    def _group(self, node: exp.Select, scope: _Scope) -> tuple[str, list[str], list[str]]:
        group = node.args.get("group")
        keys = ", ".join(self.expr(e, scope) for e in group.expressions) if group else ""
        return self.t["group_by"], [self.t["group"].format(keys=keys)], []

    def _having(self, node: exp.Select, scope: _Scope) -> tuple[str, list[str], list[str]]:
        having = node.args.get("having")
        return self.t["having"], [self.predicate(having.this, scope)] if having else [], []

    def _order(self, node: exp.Select, scope: _Scope) -> tuple[str, list[str], list[str]]:
        order = node.args.get("order")
        lines = []
        for item in order.expressions if order else []:
            target = item.this if isinstance(item, exp.Ordered) else item
            desc = bool(item.args.get("desc")) if isinstance(item, exp.Ordered) else False
            direction = self.t["desc" if desc else "asc"]
            lines.append(self.t["order"].format(expr=self.expr(target, scope), direction=direction))
        return self.t["order_by"], lines, []

    def _limit(self, node: exp.Expr, limit_added: bool) -> tuple[str, list[str], list[str]]:
        limit = node.args.get("limit")
        value = limit.expression if limit is not None else None
        n = value.sql() if value is not None else "?"
        note = self.t["limit_added"] if limit_added else ""
        return self.t["limit"], [self.t["limit_n"].format(n=n) + note], []


def _scope_aliases(node: exp.Expr | None) -> dict[str, str]:
    aliases: dict[str, str] = {}
    if not isinstance(node, exp.Select):
        return aliases
    for table in node.find_all(exp.Table):
        if table.find_ancestor(exp.Select) is node:
            aliases[(table.alias or table.name).lower()] = table.name
    return aliases


def _set_parts(tree: exp.Expr) -> list[exp.Expr]:
    """The SELECTs of a (possibly nested) set operation, left to right."""
    if isinstance(tree, exp.SetOperation):
        return _set_parts(tree.this) + _set_parts(tree.expression)
    return [tree]


def annotate(
    sql: str,
    *,
    dialect: str,
    catalog: SchemaCatalog,
    glossary: Glossary,
    question: str = "",
    locale: Locale = "es",
    limit_added: bool = False,
) -> AnnotatedSQL:
    tree = sqlglot.parse_one(sql, dialect=dialect)
    describer = _Describer(catalog, glossary, question, locale)
    # The main query may be a set operation: its SELECTs are described in order.
    parts = [_Scope("", node, aliases=_scope_aliases(node)) for node in _set_parts(tree)]
    part = 0
    scopes: dict[str, _Scope] = {}
    for cte in tree.find_all(exp.CTE):
        body = cte.this
        scopes[cte.alias_or_name] = _Scope(cte.alias_or_name, body, aliases=_scope_aliases(body))

    breaks = _breaks(sql, dialect)
    pieces: list[str] = []
    clauses: list[Clause] = []
    cursor = 0
    for i, brk in enumerate(breaks):
        end = breaks[i + 1].pos if i + 1 < len(breaks) else len(sql)
        text = sql[brk.pos : end].strip()
        if not text:
            continue
        prefix = ("\n" if pieces else "") + " " * brk.indent
        start = cursor + len(prefix)
        pieces.append(prefix + text)
        cursor = start + len(text)
        if not brk.scope and brk.kind == "set_op":
            part = min(part + 1, len(parts) - 1)
        scope = parts[part] if not brk.scope else scopes.get(brk.scope) or _Scope(brk.scope, None)
        title, details, rules = describer.describe(
            brk.kind, scope, limit_added and not brk.scope, tree
        )
        clauses.append(
            Clause(
                brk.kind,
                brk.scope,
                start,
                cursor,
                title,
                tuple(d for d in details if d),
                tuple(rules),
            )
        )
    return AnnotatedSQL("".join(pieces), tuple(clauses))
