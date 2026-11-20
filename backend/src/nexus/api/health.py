"""Liveness and readiness endpoints."""

from __future__ import annotations

from typing import Literal

from fastapi import APIRouter, Request, Response, status
from pydantic import BaseModel

from nexus import __version__
from nexus.health.checks import HealthCheck, run_checks

router = APIRouter(prefix="/api/health", tags=["health"])


class LiveResponse(BaseModel):
    status: Literal["alive"]
    version: str


class CheckOut(BaseModel):
    ok: bool
    latency_ms: float
    detail: dict[str, object]


class ReadyResponse(BaseModel):
    status: Literal["ready", "not_ready"]
    version: str
    checks: dict[str, CheckOut]


@router.get("/live")
async def live() -> LiveResponse:
    """Process is up. No dependency checks (used for restarts, not routing)."""
    return LiveResponse(status="alive", version=__version__)


@router.get(
    "/ready",
    responses={status.HTTP_503_SERVICE_UNAVAILABLE: {"model": ReadyResponse}},
)
async def ready(request: Request, response: Response) -> ReadyResponse:
    """All dependencies usable: app DB (+extensions), demo DB via read-only role, Ollama models."""
    checks: list[HealthCheck] = request.app.state.health_checks
    results = await run_checks(checks, timeout_s=request.app.state.health_timeout_s)
    all_ok = all(result.ok for result in results)
    if not all_ok:
        response.status_code = status.HTTP_503_SERVICE_UNAVAILABLE
    return ReadyResponse(
        status="ready" if all_ok else "not_ready",
        version=__version__,
        checks={
            r.name: CheckOut(ok=r.ok, latency_ms=r.latency_ms, detail=r.detail) for r in results
        },
    )
