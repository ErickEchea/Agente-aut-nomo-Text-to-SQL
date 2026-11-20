"""Dependency checks used by ``/api/health/ready``.

Each check returns a :class:`CheckResult` and never raises: failures are data, so one broken
dependency cannot hide the state of the others.
"""

from __future__ import annotations

import asyncio
import time
from collections.abc import Sequence
from dataclasses import dataclass, field
from typing import Protocol

import httpx
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine

REQUIRED_APP_EXTENSIONS = ("vector", "pg_trgm", "unaccent")


@dataclass(frozen=True, slots=True)
class CheckResult:
    name: str
    ok: bool
    latency_ms: float
    detail: dict[str, object] = field(default_factory=dict)


class HealthCheck(Protocol):
    name: str

    async def probe(self) -> dict[str, object]:
        """Return details on success; raise on failure (``run_check`` converts it)."""
        ...


class CheckFailedError(Exception):
    """A dependency answered, but not in the required state."""

    def __init__(self, message: str, detail: dict[str, object] | None = None) -> None:
        super().__init__(message)
        self.detail = detail or {}


class AppDatabaseCheck:
    """App DB reachable and the extensions the RAG layer needs are installed."""

    name = "app_db"

    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def probe(self) -> dict[str, object]:
        async with self._engine.connect() as conn:
            rows = await conn.execute(
                text("SELECT extname FROM pg_extension WHERE extname = ANY(:names)"),
                {"names": list(REQUIRED_APP_EXTENSIONS)},
            )
            installed = sorted(row[0] for row in rows)
        missing = sorted(set(REQUIRED_APP_EXTENSIONS) - set(installed))
        if missing:
            raise CheckFailedError("missing extensions", {"missing_extensions": missing})
        return {"extensions": installed}


class DemoDatabaseCheck:
    """Demo DB reachable through the agent's role, and that role really is read-only by default."""

    name = "demo_db"

    def __init__(self, engine: AsyncEngine) -> None:
        self._engine = engine

    async def probe(self) -> dict[str, object]:
        async with self._engine.connect() as conn:
            read_only = (
                await conn.execute(text("SHOW default_transaction_read_only"))
            ).scalar_one()
            tables = (
                await conn.execute(
                    text(
                        "SELECT count(*) FROM information_schema.tables "
                        "WHERE table_schema = 'retail' AND table_type = 'BASE TABLE'"
                    )
                )
            ).scalar_one()
        detail: dict[str, object] = {"read_only": read_only == "on", "retail_tables": int(tables)}
        if read_only != "on":
            raise CheckFailedError("agent role is not read-only by default", detail)
        if int(tables) == 0:
            raise CheckFailedError("retail schema has no visible tables (seed not loaded?)", detail)
        return detail


class OllamaCheck:
    """Ollama reachable and every required model pulled."""

    name = "ollama"

    def __init__(self, client: httpx.AsyncClient, required_models: Sequence[str]) -> None:
        self._client = client
        self._required = tuple(required_models)

    async def probe(self) -> dict[str, object]:
        response = await self._client.get("/api/tags")
        response.raise_for_status()
        payload = response.json()
        available = {str(model["name"]) for model in payload.get("models", [])}
        missing = [model for model in self._required if model not in available]
        detail: dict[str, object] = {"required": list(self._required), "missing": missing}
        if missing:
            raise CheckFailedError("required models not pulled", detail)
        return detail


async def run_check(check: HealthCheck, timeout_s: float) -> CheckResult:
    started = time.perf_counter()
    try:
        async with asyncio.timeout(timeout_s):
            detail = await check.probe()
        ok = True
    except CheckFailedError as exc:
        ok, detail = False, {"error": str(exc), **exc.detail}
    except TimeoutError:
        ok, detail = False, {"error": f"timed out after {timeout_s}s"}
    except Exception as exc:  # any failure must be reported, not raised
        ok, detail = False, {"error": type(exc).__name__, "message": str(exc)[:300]}
    latency_ms = round((time.perf_counter() - started) * 1000, 2)
    return CheckResult(name=check.name, ok=ok, latency_ms=latency_ms, detail=detail)


async def run_checks(checks: Sequence[HealthCheck], timeout_s: float = 5.0) -> list[CheckResult]:
    return list(await asyncio.gather(*(run_check(check, timeout_s) for check in checks)))
