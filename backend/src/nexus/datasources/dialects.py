"""Per-engine knowledge (ADR-0013): SQL dialect, read-only session setup, prompt rules and error
classification for PostgreSQL, MySQL 8 and SQLite.

Everything engine-specific lives here so the agent, the executor and the optimizer stay generic.
"""

from __future__ import annotations

import datetime as dt
import re
from dataclasses import dataclass, field
from typing import Final, Literal

Kind = Literal["postgresql", "mysql", "sqlite"]
KINDS: Final[tuple[Kind, ...]] = ("postgresql", "mysql", "sqlite")


@dataclass(frozen=True, slots=True)
class ErrorClass:
    """How the agent should treat a database error."""

    code: str  # SQLSTATE for PostgreSQL; "MY<errno>" for MySQL; "SQLITE_*" for SQLite
    repairable: bool  # rewriting the SQL may help (unknown column, syntax, ...)
    timeout: bool = False


@dataclass(frozen=True, slots=True)
class DialectProfile:
    kind: Kind
    sqlglot: str
    label: str
    driver: str  # SQLAlchemy async driver name
    default_port: int | None
    date_hint: str  # how dates must be written in generated SQL (prompt)
    tips: tuple[str, ...]  # engine-specific prompt rules (Spanish, like the rest of the prompts)
    extra_functions: frozenset[str] = field(default_factory=frozenset)

    def date_literal(self, value: dt.date) -> str:
        return f"'{value.isoformat()}'" if self.kind == "sqlite" else f"DATE '{value.isoformat()}'"


POSTGRESQL = DialectProfile(
    kind="postgresql",
    sqlglot="postgres",
    label="PostgreSQL",
    driver="postgresql+asyncpg",
    default_port=5432,
    date_hint="DATE 'AAAA-MM-DD'",
    # No extra rules: the PostgreSQL prompt stays byte-identical to the one validated end to end
    # (a single added line changed the 7B model's greedy output on the reference question).
    tips=(),
)

MYSQL = DialectProfile(
    kind="mysql",
    sqlglot="mysql",
    label="MySQL 8",
    driver="mysql+aiomysql",
    default_port=3306,
    date_hint="DATE 'AAAA-MM-DD'",
    tips=(
        "Dialecto MySQL 8: agrupa por periodo con DATE_FORMAT(col, '%Y-%m') o YEAR()/MONTH().",
        "No existen ILIKE ni los casts con '::'; usa CAST(x AS ...) y LIKE.",
    ),
    extra_functions=frozenset(
        {
            "date_format",
            "str_to_date",
            "datediff",
            "timestampdiff",
            "ifnull",
            "field",
            "weekofyear",
            "dayofweek",
            "dayofmonth",
            "quarter",
            "last_day",
            "date_add",
            "date_sub",
            "curdate",
            "yearweek",
            "month",
            "year",
            "day",
            "hour",
            "concat_ws",
            "group_concat",
            "round",
            "truncate",
        }
    ),
)

SQLITE = DialectProfile(
    kind="sqlite",
    sqlglot="sqlite",
    label="SQLite",
    driver="sqlite+aiosqlite",
    default_port=None,
    date_hint="'AAAA-MM-DD' (texto ISO)",
    tips=(
        "Dialecto SQLite: las fechas son texto ISO; compáralas con literales de texto "
        "('2026-07-01'), "
        "nunca con DATE '...'.",
        "Agrupa por mes con strftime('%Y-%m', col) y por año con strftime('%Y', col).",
        "No existen ILIKE, '::', date_trunc ni EXTRACT.",
    ),
    extra_functions=frozenset(
        {
            "strftime",
            "julianday",
            "date",
            "datetime",
            "time",
            "unixepoch",
            "printf",
            "ifnull",
            "instr",
            "substr",
            "total",
            "group_concat",
            "iif",
            "round",
        }
    ),
)

PROFILES: Final[dict[Kind, DialectProfile]] = {
    "postgresql": POSTGRESQL,
    "mysql": MYSQL,
    "sqlite": SQLITE,
}


def profile_for(kind: str) -> DialectProfile:
    if kind not in PROFILES:
        raise ValueError(f"unsupported database kind {kind!r}")
    return PROFILES[kind]


# ---- error classification ------------------------------------------------------------------

_PG_REPAIRABLE: Final = ("42", "22", "21")
_PG_TIMEOUT: Final = frozenset({"57014", "55P03"})
_PG_PRIVILEGE: Final = "42501"

# MySQL error numbers the model can fix by rewriting (unknown column/table, syntax, ambiguity, ...)
_MY_REPAIRABLE: Final = frozenset(
    {1052, 1054, 1055, 1056, 1060, 1064, 1066, 1111, 1140, 1146, 1222, 1241, 1242, 1248, 1305,
     1317, 1365, 1367, 1582, 1583, 1630, 3065}
)  # fmt: skip
_MY_TIMEOUT: Final = frozenset({3024, 1969})  # max_execution_time exceeded

_SQLITE_REPAIRABLE = re.compile(
    r"no such (column|table|function)|syntax error|ambiguous column|misuse of aggregate|"
    r"wrong number of arguments|incomplete input|near \"",
    re.IGNORECASE,
)


def classify_error(
    kind: Kind, *, sqlstate: str | None, errno: int | None, message: str
) -> ErrorClass:
    if kind == "postgresql":
        code = sqlstate or "unknown"
        return ErrorClass(
            code,
            repairable=code != _PG_PRIVILEGE and code.startswith(_PG_REPAIRABLE),
            timeout=code in _PG_TIMEOUT,
        )
    if kind == "mysql":
        number = errno or 0
        return ErrorClass(
            f"MY{number}", repairable=number in _MY_REPAIRABLE, timeout=number in _MY_TIMEOUT
        )
    lowered = message.lower()
    if "interrupted" in lowered:
        return ErrorClass("SQLITE_INTERRUPT", repairable=False, timeout=True)
    if "readonly" in lowered or "read-only" in lowered or "query_only" in lowered:
        return ErrorClass("SQLITE_READONLY", repairable=False)
    if _SQLITE_REPAIRABLE.search(message):
        return ErrorClass("SQLITE_ERROR", repairable=True)
    return ErrorClass("SQLITE_ERROR", repairable=False)
