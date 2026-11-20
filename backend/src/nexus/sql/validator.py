"""AST-based SQL validation — ADR-0005 layer A. Never regex.

The validator is deny-by-default: only a single read query over allow-listed tables, using known
functions, passes. Its output is SQL *re-generated from the AST* (comments and odd whitespace never
reach the database) with an enforced ``LIMIT``.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import StrEnum

import sqlglot
from sqlglot import exp
from sqlglot.errors import ParseError

# sqlglot logs a warning when it falls back to exp.Command; we reject Command anyway.
logging.getLogger("sqlglot").setLevel(logging.ERROR)

MAX_SQL_LENGTH = 20_000


class ViolationCode(StrEnum):
    EMPTY = "empty"
    TOO_LONG = "too_long"
    PARSE_ERROR = "parse_error"
    MULTIPLE_STATEMENTS = "multiple_statements"
    NOT_A_QUERY = "not_a_query"
    FORBIDDEN_STATEMENT = "forbidden_statement"
    SELECT_INTO = "select_into"
    LOCKING_CLAUSE = "locking_clause"
    FORBIDDEN_FUNCTION = "forbidden_function"
    UNKNOWN_FUNCTION = "unknown_function"
    FORBIDDEN_TABLE = "forbidden_table"
    FORBIDDEN_SCHEMA = "forbidden_schema"
    TABLE_FUNCTION = "table_function"


class SQLValidationError(Exception):
    """Machine-readable rejection; ``code`` feeds the repair prompt and the UI message."""

    def __init__(self, code: ViolationCode, detail: str) -> None:
        super().__init__(f"{code.value}: {detail}")
        self.code = code
        self.detail = detail


def _classes(*names: str) -> tuple[type[exp.Expression], ...]:
    """Resolve sqlglot classes by name, tolerating ones a future version renames or drops."""
    return tuple(getattr(exp, n) for n in names if isinstance(getattr(exp, n, None), type))


# Any of these anywhere in the tree rejects the query (e.g. a DELETE hidden inside a CTE).
FORBIDDEN_NODES: tuple[type[exp.Expression], ...] = _classes(
    "DML", "DDL", "Insert", "Update", "Delete", "Merge", "Copy", "Create", "Drop", "Alter",
    "TruncateTable", "Command", "Set", "Transaction", "Commit", "Rollback", "Grant", "Revoke",
    "Lock", "Use", "Pragma", "Kill", "LoadData", "Analyze", "Attach", "Detach", "Install",
    "Export", "Cache", "Uncache", "Refresh", "Declare", "Execute", "ExecuteSql", "Comment",
    "Describe", "Show", "Summarize", "UserDefinedFunction",
)  # fmt: skip

# Function names that are never acceptable, even if a parser types them (lower-case).
DENIED_FUNCTIONS: frozenset[str] = frozenset(
    {
        # PostgreSQL: sleeping, file system, large objects, remote access, config, signals, locks
        "pg_sleep", "pg_sleep_for", "pg_sleep_until", "pg_read_file", "pg_read_binary_file",
        "pg_ls_dir", "pg_stat_file", "pg_ls_logdir", "pg_ls_waldir", "pg_ls_tmpdir",
        "pg_ls_archive_statusdir", "lo_import", "lo_export", "lo_create", "lo_creat", "lo_open",
        "lo_unlink", "lo_put", "lo_get", "lo_from_bytea", "loread", "lowrite", "dblink",
        "dblink_exec", "dblink_connect", "dblink_send_query", "set_config", "current_setting",
        "pg_terminate_backend", "pg_cancel_backend", "pg_reload_conf", "pg_rotate_logfile",
        "pg_promote", "pg_advisory_lock", "pg_advisory_xact_lock", "pg_try_advisory_lock",
        "pg_advisory_lock_shared", "pg_advisory_unlock", "pg_advisory_unlock_all", "txid_current",
        "pg_current_xact_id", "nextval", "setval", "currval", "lastval", "query_to_xml",
        "query_to_json", "xpath", "pg_logical_emit_message", "pg_switch_wal",
        "pg_create_restore_point", "pg_notify",
        # MySQL / SQLite equivalents (multi-DB, Phase 5)
        "sleep", "benchmark", "load_file", "load_extension", "get_lock", "release_lock",
    }
)  # fmt: skip

# Functions sqlglot does not model (parsed as exp.Anonymous) that analysts legitimately use.
ALLOWED_ANONYMOUS_FUNCTIONS: frozenset[str] = frozenset(
    {
        "age", "make_date", "make_timestamp", "make_interval", "date_bin", "justify_interval",
        "justify_days", "to_date", "to_timestamp", "to_number", "isfinite", "initcap", "btrim",
        "ltrim", "rtrim", "lpad", "rpad", "regexp_replace", "regexp_match", "translate",
        "format", "concat_ws", "unaccent", "width_bucket", "ntile", "percent_rank", "cume_dist",
        "dense_rank", "rank", "row_number", "lag", "lead", "first_value", "last_value",
        "nth_value", "mode", "bool_and", "bool_or", "every", "array_agg", "jsonb_agg",
        "json_agg", "jsonb_build_object", "json_build_object", "div", "mod", "sign", "trunc",
        "cbrt", "degrees", "radians", "extract", "date_part", "string_to_array", "array_length",
        "cardinality", "num_nonnulls", "num_nulls", "scale", "trim_scale",
    }
)  # fmt: skip

ALLOWED_TABLE_FUNCTIONS: frozenset[str] = frozenset({"generate_series", "unnest"})
TABLE_FUNCTION_NODES: tuple[type[exp.Expression], ...] = _classes(
    "GenerateSeries", "ExplodingGenerateSeries", "Unnest"
)


@dataclass(frozen=True, slots=True)
class ValidationPolicy:
    """What a connection allows. Table and schema names are lower-case."""

    allowed_tables: frozenset[str]
    allowed_schemas: frozenset[str] = frozenset({"retail"})
    max_rows: int = 1000
    dialect: str = "postgres"
    extra_allowed_functions: frozenset[str] = field(default_factory=frozenset)


@dataclass(frozen=True, slots=True)
class ValidatedSQL:
    sql: str  # regenerated from the AST, comments stripped, LIMIT enforced
    tables: tuple[str, ...]
    limit_applied: int
    limit_was_added: bool


def _function_name(node: exp.Func) -> str:
    if isinstance(node, exp.Anonymous):
        return str(node.name).lower()
    return str(node.sql_name()).lower()


def _cte_names(tree: exp.Expr) -> set[str]:
    return {cte.alias_or_name.lower() for cte in tree.find_all(exp.CTE)}


def _check_nodes(tree: exp.Expr) -> None:
    for node in tree.walk():
        # Specific checks first, so the error code names the actual problem.
        if isinstance(node, exp.Select) and node.args.get("locks"):
            raise SQLValidationError(
                ViolationCode.LOCKING_CLAUSE, "FOR UPDATE/SHARE is not allowed"
            )
        if isinstance(node, exp.Into):
            raise SQLValidationError(ViolationCode.SELECT_INTO, "SELECT ... INTO is not allowed")
        if isinstance(node, FORBIDDEN_NODES):
            raise SQLValidationError(
                ViolationCode.FORBIDDEN_STATEMENT, f"{type(node).__name__} is not allowed"
            )


def _check_functions(tree: exp.Expr, policy: ValidationPolicy) -> None:
    for func in tree.find_all(exp.Func):
        name = _function_name(func)
        if name in DENIED_FUNCTIONS:
            raise SQLValidationError(ViolationCode.FORBIDDEN_FUNCTION, f"{name}() is not allowed")
        if isinstance(func, exp.Anonymous) and name not in (
            ALLOWED_ANONYMOUS_FUNCTIONS | policy.extra_allowed_functions
        ):
            raise SQLValidationError(
                ViolationCode.UNKNOWN_FUNCTION, f"{name}() is not allow-listed"
            )


def _check_tables(tree: exp.Expr, policy: ValidationPolicy) -> tuple[str, ...]:
    ctes = _cte_names(tree)
    used: list[str] = []
    for table in tree.find_all(exp.Table):
        target = table.this
        if isinstance(target, exp.Func):
            name = _function_name(target)
            typed_ok = isinstance(target, TABLE_FUNCTION_NODES)
            if not typed_ok and name not in ALLOWED_TABLE_FUNCTIONS:
                raise SQLValidationError(ViolationCode.TABLE_FUNCTION, f"{name} as a table")
            continue
        if not isinstance(target, exp.Identifier):
            raise SQLValidationError(ViolationCode.FORBIDDEN_TABLE, "unsupported table reference")
        # Quoted identifiers are case-sensitive in PostgreSQL: "VENTAS" is not ventas.
        name = target.name if target.quoted else target.name.lower()
        schema = table.db.lower() if table.db else ""
        if table.catalog:
            raise SQLValidationError(
                ViolationCode.FORBIDDEN_SCHEMA, f"cross-database reference {table.sql()}"
            )
        if not schema and name.lower() in ctes:
            continue
        if schema and schema not in policy.allowed_schemas:
            raise SQLValidationError(ViolationCode.FORBIDDEN_SCHEMA, f"schema {schema!r}")
        if name not in policy.allowed_tables:
            raise SQLValidationError(ViolationCode.FORBIDDEN_TABLE, f"table {name!r}")
        used.append(name)
    return tuple(sorted(set(used)))


def _enforce_limit(tree: exp.Query, max_rows: int) -> tuple[exp.Query, int, bool]:
    current = tree.args.get("limit")
    if current is None:
        return tree.limit(max_rows), max_rows, True
    value = current.expression
    if isinstance(value, exp.Literal) and value.is_int and int(value.name) <= max_rows:
        return tree, int(value.name), False
    return tree.limit(max_rows), max_rows, False


def validate_sql(sql: str, policy: ValidationPolicy) -> ValidatedSQL:
    """Validate one LLM-produced query; raise :class:`SQLValidationError` on any violation."""
    text = sql.strip()
    if not text:
        raise SQLValidationError(ViolationCode.EMPTY, "no SQL provided")
    if len(text) > MAX_SQL_LENGTH:
        raise SQLValidationError(ViolationCode.TOO_LONG, f"over {MAX_SQL_LENGTH} characters")
    try:
        statements = [s for s in sqlglot.parse(text, dialect=policy.dialect) if s is not None]
    except ParseError as exc:
        raise SQLValidationError(ViolationCode.PARSE_ERROR, str(exc).splitlines()[0]) from exc
    if len(statements) != 1:
        raise SQLValidationError(
            ViolationCode.MULTIPLE_STATEMENTS, f"expected 1 statement, got {len(statements)}"
        )
    tree = statements[0]
    _check_nodes(tree)
    if not isinstance(tree, exp.Select | exp.SetOperation):
        raise SQLValidationError(ViolationCode.NOT_A_QUERY, f"{type(tree).__name__} statement")
    _check_functions(tree, policy)
    tables = _check_tables(tree, policy)
    limited, limit, added = _enforce_limit(tree, policy.max_rows)
    return ValidatedSQL(
        sql=limited.sql(dialect=policy.dialect, comments=False),
        tables=tables,
        limit_applied=limit,
        limit_was_added=added,
    )
