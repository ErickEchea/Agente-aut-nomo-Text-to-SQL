"""Read-only query execution — ADR-0005 layers B and C, per engine (ADR-0013).

Every query runs in its own read-only transaction with a time limit, on a pool dedicated to the data
source, and is always rolled back. The public API only accepts :class:`ValidatedSQL`, so raw model
output cannot reach the database by accident.

- PostgreSQL: SELECT-only role, ``SET TRANSACTION READ ONLY``, ``SET LOCAL statement_timeout``.
- MySQL 8: SELECT-only user, session ``transaction_read_only`` + ``START TRANSACTION READ ONLY``,
  ``max_execution_time``.
- SQLite: ``mode=ro`` URI, ``PRAGMA query_only``, a progress handler that aborts slow queries.
"""

from __future__ import annotations

import base64
import datetime as dt
import json
import time
import uuid
from dataclasses import dataclass
from decimal import Decimal
from typing import Final, Literal

from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncConnection, AsyncEngine

from nexus.datasources.dialects import Kind, classify_error
from nexus.sql.validator import ValidatedSQL

JsonScalar = str | int | float | bool | None

QUERY_CANCELED: Final = "57014"  # PostgreSQL statement_timeout
LOCK_NOT_AVAILABLE: Final = "55P03"  # PostgreSQL lock_timeout
INSUFFICIENT_PRIVILEGE: Final = "42501"
READ_ONLY_TRANSACTION: Final = "25006"
SQLITE_PROGRESS_STEPS: Final = 1000  # VM instructions between deadline checks


@dataclass(frozen=True, slots=True)
class QueryResult:
    columns: tuple[str, ...]
    rows: list[tuple[JsonScalar, ...]]
    row_count: int
    truncated: bool
    duration_ms: float


class QueryExecutionError(Exception):
    def __init__(
        self,
        message: str,
        *,
        sqlstate: str | None,
        duration_ms: float,
        repairable: bool | None = None,
        timeout: bool = False,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.sqlstate = sqlstate
        self.duration_ms = duration_ms
        self.timeout = timeout
        self._repairable = repairable

    @property
    def repairable(self) -> bool:
        """Whether rewriting the SQL may help (as opposed to timeouts or privilege errors)."""
        if self._repairable is not None:
            return self._repairable
        return classify_error(
            "postgresql", sqlstate=self.sqlstate, errno=None, message=self.message
        ).repairable


def to_json_scalar(value: object) -> JsonScalar:
    """Convert a driver value into something JSON (and the UI) can carry losslessly enough."""
    match value:
        case None | bool() | int() | str() | float():
            return value
        case Decimal():
            return float(value)
        case dt.datetime() | dt.date() | dt.time():
            return value.isoformat()
        case dt.timedelta():
            return value.total_seconds()
        case uuid.UUID():
            return str(value)
        case bytes() | bytearray() | memoryview():
            return base64.b64encode(bytes(value)).decode("ascii")
        case list() | dict() | tuple():
            # json/jsonb/arrays arrive decoded by the driver: re-encode as real JSON, not repr().
            return json.dumps(value, ensure_ascii=False, default=str)
        case _:
            return str(value)


ExplainFormat = Literal["postgres_json", "mysql_json", "sqlite_plan"]


@dataclass(frozen=True, slots=True)
class ExplainOutput:
    format: ExplainFormat
    plan: object  # parsed JSON (PostgreSQL/MySQL) or the EXPLAIN QUERY PLAN rows (SQLite)


class ReadOnlyExecutor:
    def __init__(
        self,
        engine: AsyncEngine,
        *,
        kind: Kind = "postgresql",
        statement_timeout_ms: int = 15_000,
        lock_timeout_ms: int = 2_000,
        max_rows: int = 1000,
    ) -> None:
        self._engine = engine
        self.kind: Kind = kind
        self._statement_timeout_ms = int(statement_timeout_ms)
        self._lock_timeout_ms = int(lock_timeout_ms)
        self.max_rows = max_rows

    async def execute(self, query: ValidatedSQL) -> QueryResult:
        return await self._execute_sql(query.sql)

    async def explain(self, query: ValidatedSQL) -> ExplainOutput:
        """The engine's plan for a validated query, without running it (no ANALYZE)."""
        if self.kind == "postgresql":
            result = await self._execute_sql(f"EXPLAIN (FORMAT JSON) {query.sql}")
            return ExplainOutput("postgres_json", _json_cell(result))
        if self.kind == "mysql":
            result = await self._execute_sql(f"EXPLAIN FORMAT=JSON {query.sql}")
            return ExplainOutput("mysql_json", _json_cell(result))
        result = await self._execute_sql(f"EXPLAIN QUERY PLAN {query.sql}")
        return ExplainOutput("sqlite_plan", [list(row) for row in result.rows])

    async def explain_with_hypothetical_index(
        self, query: ValidatedSQL, create_index_sql: str
    ) -> object:
        """PostgreSQL + HypoPG: the plan as if ``create_index_sql`` existed. Nothing is written:
        hypothetical indexes live in this backend's memory and are reset before the connection
        goes back to the pool. ``create_index_sql`` is built by the optimizer from catalog
        identifiers, never by the model."""
        if self.kind != "postgresql":
            raise ValueError("hypothetical indexes need PostgreSQL with HypoPG")
        statements = [
            # The DDL text is quoted as a literal; it never comes from the model.
            (f"SELECT * FROM hypopg.hypopg_create_index({_pg_literal(create_index_sql)})", False),  # noqa: S608
            (f"EXPLAIN (FORMAT JSON) {query.sql}", True),
        ]
        result = await self._execute_sql("", prelude=statements)
        return _json_cell(result)

    async def _execute_sql(
        self,
        sql: str,
        *,
        prelude: list[tuple[str, bool]] | None = None,
    ) -> QueryResult:
        """Run SQL in a read-only, time-boxed, always-rolled-back transaction.

        Private on purpose: callers go through :meth:`execute`, which requires validated SQL. The
        security test-suite calls this directly to prove the database layers hold on their own.
        ``prelude`` (optimizer only) runs fixed statements; the one flagged True returns rows. Its
        connection is discarded afterwards: HypoPG state is per backend and survives ROLLBACK.
        """
        started = time.perf_counter()
        try:
            async with self._engine.connect() as conn:
                if self.kind == "postgresql":
                    try:
                        columns, raw = await self._run_postgres(conn, sql, prelude)
                    finally:
                        if prelude is not None:
                            await conn.invalidate()
                elif self.kind == "mysql":
                    columns, raw = await self._run_mysql(conn, sql)
                else:
                    columns, raw = await self._run_sqlite(conn, sql, started)
        except DBAPIError as exc:
            raise self._error(exc, started) from exc

        truncated = len(raw) > self.max_rows
        rows = [tuple(to_json_scalar(v) for v in row) for row in raw[: self.max_rows]]
        return QueryResult(
            columns=columns,
            rows=rows,
            row_count=len(rows),
            truncated=truncated,
            duration_ms=round((time.perf_counter() - started) * 1000, 2),
        )

    async def _fetch(
        self, conn: AsyncConnection, sql: str
    ) -> tuple[tuple[str, ...], list[tuple[object, ...]]]:
        result = await conn.exec_driver_sql(sql)
        if not result.returns_rows:
            return (), []
        return tuple(result.keys()), [tuple(r) for r in result.fetchmany(self.max_rows + 1)]

    async def _run_postgres(
        self,
        conn: AsyncConnection,
        sql: str,
        prelude: list[tuple[str, bool]] | None,
    ) -> tuple[tuple[str, ...], list[tuple[object, ...]]]:
        transaction = await conn.begin()
        try:
            await conn.exec_driver_sql("SET TRANSACTION READ ONLY")
            # Integers formatted by us, never user input.
            await conn.exec_driver_sql(
                f"SET LOCAL statement_timeout = {self._statement_timeout_ms}"
            )
            await conn.exec_driver_sql(f"SET LOCAL lock_timeout = {self._lock_timeout_ms}")
            if prelude is None:
                return await self._fetch(conn, sql)
            out: tuple[tuple[str, ...], list[tuple[object, ...]]] = ((), [])
            for statement, keep in prelude:
                fetched = await self._fetch(conn, statement)
                if keep:
                    out = fetched
            return out
        finally:
            await transaction.rollback()

    async def _run_mysql(
        self, conn: AsyncConnection, sql: str
    ) -> tuple[tuple[str, ...], list[tuple[object, ...]]]:
        # The transaction is managed explicitly so it can be opened READ ONLY.
        conn = await conn.execution_options(isolation_level="AUTOCOMMIT", no_parameters=True)
        await conn.exec_driver_sql(f"SET SESSION max_execution_time = {self._statement_timeout_ms}")
        await conn.exec_driver_sql(
            f"SET SESSION innodb_lock_wait_timeout = {max(1, self._lock_timeout_ms // 1000)}"
        )
        # A READ ONLY transaction alone does not stop DDL in MySQL (DDL commits implicitly and runs
        # outside it); the session-level flag does. Both are set (measured in the MySQL tests).
        await conn.exec_driver_sql("SET SESSION transaction_read_only = ON")
        await conn.exec_driver_sql("START TRANSACTION READ ONLY")
        try:
            return await self._fetch(conn, sql)
        finally:
            await conn.exec_driver_sql("ROLLBACK")

    async def _run_sqlite(
        self, conn: AsyncConnection, sql: str, started: float
    ) -> tuple[tuple[str, ...], list[tuple[object, ...]]]:
        deadline = started + self._statement_timeout_ms / 1000

        def over_time() -> int:
            return 1 if time.perf_counter() > deadline else 0

        raw = await conn.get_raw_connection()
        driver = raw.driver_connection
        if driver is None:  # pragma: no cover — aiosqlite always exposes its connection
            raise RuntimeError("SQLite driver connection unavailable")
        await driver.set_progress_handler(over_time, SQLITE_PROGRESS_STEPS)
        transaction = await conn.begin()
        try:
            await conn.exec_driver_sql("PRAGMA query_only = ON")
            return await self._fetch(conn, sql)
        finally:
            await transaction.rollback()
            await driver.set_progress_handler(None, SQLITE_PROGRESS_STEPS)

    def _error(self, exc: DBAPIError, started: float) -> QueryExecutionError:
        duration = (time.perf_counter() - started) * 1000
        orig = exc.orig
        sqlstate = getattr(orig, "sqlstate", None) or getattr(orig, "pgcode", None)
        args: tuple[object, ...] = tuple(getattr(orig, "args", ()))
        errno = args[0] if args and isinstance(args[0], int) else None
        message = str(orig).splitlines()[0] if orig is not None else str(exc)
        # Strip the driver's class prefix: "<class 'asyncpg...'>: message".
        message = message.split(">: ", 1)[-1]
        if errno is not None and len(args) > 1:
            message = str(args[1])
        kind = classify_error(self.kind, sqlstate=sqlstate, errno=errno, message=message)
        return QueryExecutionError(
            message,
            sqlstate=kind.code,
            duration_ms=duration,
            repairable=kind.repairable,
            timeout=kind.timeout,
        )


def _json_cell(result: QueryResult) -> object:
    if not result.rows or not isinstance(result.rows[0][0], str):
        return None
    plan: object = json.loads(result.rows[0][0])
    return plan


def _pg_literal(text: str) -> str:
    return "'" + text.replace("'", "''") + "'"
