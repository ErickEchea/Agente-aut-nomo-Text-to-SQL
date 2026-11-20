"""Read-only query execution — ADR-0005 layers B and C.

Every query runs in its own ``READ ONLY`` transaction with local timeouts on a pool dedicated to the
data source, and is always rolled back. The public API only accepts :class:`ValidatedSQL`, so raw
model output cannot reach the database by accident.
"""

from __future__ import annotations

import base64
import datetime as dt
import json
import time
import uuid
from dataclasses import dataclass
from decimal import Decimal
from typing import Final

from sqlalchemy.exc import DBAPIError
from sqlalchemy.ext.asyncio import AsyncEngine

from nexus.sql.validator import ValidatedSQL

JsonScalar = str | int | float | bool | None

QUERY_CANCELED: Final = "57014"  # statement_timeout
LOCK_NOT_AVAILABLE: Final = "55P03"  # lock_timeout
INSUFFICIENT_PRIVILEGE: Final = "42501"
READ_ONLY_TRANSACTION: Final = "25006"
# Errors the model can plausibly fix by rewriting the query (bad column, bad type, syntax, ...).
REPAIRABLE_CLASSES: Final = ("42", "22", "21")


@dataclass(frozen=True, slots=True)
class QueryResult:
    columns: tuple[str, ...]
    rows: list[tuple[JsonScalar, ...]]
    row_count: int
    truncated: bool
    duration_ms: float


class QueryExecutionError(Exception):
    def __init__(self, message: str, *, sqlstate: str | None, duration_ms: float) -> None:
        super().__init__(message)
        self.message = message
        self.sqlstate = sqlstate
        self.duration_ms = duration_ms

    @property
    def repairable(self) -> bool:
        """Whether rewriting the SQL may help (as opposed to timeouts or privilege errors)."""
        if self.sqlstate is None or self.sqlstate == INSUFFICIENT_PRIVILEGE:
            return False
        return self.sqlstate.startswith(REPAIRABLE_CLASSES)


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


class ReadOnlyExecutor:
    def __init__(
        self,
        engine: AsyncEngine,
        *,
        statement_timeout_ms: int = 15_000,
        lock_timeout_ms: int = 2_000,
        max_rows: int = 1000,
    ) -> None:
        self._engine = engine
        self._statement_timeout_ms = int(statement_timeout_ms)
        self._lock_timeout_ms = int(lock_timeout_ms)
        self.max_rows = max_rows

    async def execute(self, query: ValidatedSQL) -> QueryResult:
        return await self._execute_sql(query.sql)

    async def explain(self, query: ValidatedSQL) -> object:
        """EXPLAIN (FORMAT JSON) without ANALYZE: plans only, never runs the query."""
        result = await self._execute_sql(f"EXPLAIN (FORMAT JSON) {query.sql}")
        if not result.rows or not isinstance(result.rows[0][0], str):
            return None
        plan: object = json.loads(result.rows[0][0])
        return plan

    async def _execute_sql(self, sql: str) -> QueryResult:
        """Run SQL in a read-only, time-boxed, always-rolled-back transaction.

        Private on purpose: callers go through :meth:`execute`, which requires validated SQL. The
        security test-suite calls this directly to prove the database layers hold on their own.
        """
        started = time.perf_counter()
        try:
            async with self._engine.connect() as conn:
                transaction = await conn.begin()
                try:
                    await conn.exec_driver_sql("SET TRANSACTION READ ONLY")
                    # Integers formatted by us, never user input.
                    await conn.exec_driver_sql(
                        f"SET LOCAL statement_timeout = {self._statement_timeout_ms}"
                    )
                    await conn.exec_driver_sql(f"SET LOCAL lock_timeout = {self._lock_timeout_ms}")
                    result = await conn.exec_driver_sql(sql)
                    columns = tuple(result.keys()) if result.returns_rows else ()
                    raw = result.fetchmany(self.max_rows + 1) if result.returns_rows else []
                finally:
                    await transaction.rollback()
        except DBAPIError as exc:
            duration = (time.perf_counter() - started) * 1000
            orig = exc.orig
            sqlstate = getattr(orig, "sqlstate", None) or getattr(orig, "pgcode", None)
            message = str(orig).splitlines()[0] if orig is not None else str(exc)
            # Strip the driver's class prefix: "<class 'asyncpg...'>: message".
            message = message.split(">: ", 1)[-1]
            raise QueryExecutionError(message, sqlstate=sqlstate, duration_ms=duration) from exc

        truncated = len(raw) > self.max_rows
        rows = [tuple(to_json_scalar(v) for v in row) for row in raw[: self.max_rows]]
        return QueryResult(
            columns=columns,
            rows=rows,
            row_count=len(rows),
            truncated=truncated,
            duration_ms=round((time.perf_counter() - started) * 1000, 2),
        )
