"""Benchmark results for the Benchmark page (Phase 6, ADR-0015/ADR-0022).

Runs are written by ``nexus-bench run``; this API only reads them. The overview shows the newest
completed full-golden-set run of each configuration and which one the selection rule picks.
"""

from __future__ import annotations

import datetime as dt
import uuid

from fastapi import APIRouter, HTTPException, status
from pydantic import BaseModel
from sqlalchemy import select

from nexus.api.deps import AuthenticatedUser, Services, Session
from nexus.bench.metrics import (
    REFERENCE_ITEMS,
    SELECTION_MARGIN,
    Summary,
    is_eligible,
    select_default,
)
from nexus.bench.runner import BenchConfig
from nexus.bench.store import latest_completed
from nexus.db.models import BenchmarkResult, BenchmarkRun

router = APIRouter(prefix="/api/benchmark", tags=["benchmark"])


class BenchmarkRunOut(BaseModel):
    id: uuid.UUID
    config: BenchConfig
    subset: str
    dataset_version: str
    git_sha: str | None
    started_at: dt.datetime
    finished_at: dt.datetime | None
    summary: Summary
    eligible: bool  # answers the reference question(s), a requirement for the default


class ServingModel(BaseModel):
    model: str
    nodes: dict[str, str]
    think: bool | None


class BenchmarkOverview(BaseModel):
    runs: list[BenchmarkRunOut]
    selected: str | None
    selection_margin: float
    reference_items: list[str]
    serving: ServingModel


class BenchmarkResultOut(BaseModel):
    item_id: str
    difficulty: str
    question: str
    correct: bool
    reason: str
    status: str
    latency_ms: float
    tokens: int
    repairs: int
    sql: list[str]
    error: str | None


class BenchmarkRunDetail(BenchmarkRunOut):
    results: list[BenchmarkResultOut]


def _run_out(run: BenchmarkRun, correct_items: set[str]) -> BenchmarkRunOut:
    return BenchmarkRunOut(
        id=run.id,
        config=BenchConfig.model_validate(run.config),
        subset=run.subset,
        dataset_version=run.dataset_version,
        git_sha=run.git_sha,
        started_at=run.started_at,
        finished_at=run.finished_at,
        summary=Summary.model_validate(run.summary),
        eligible=is_eligible(correct_items),
    )


async def _correct_reference_items(
    session: Session, run_ids: list[uuid.UUID]
) -> dict[uuid.UUID, set[str]]:
    rows = (
        await session.execute(
            select(BenchmarkResult.run_id, BenchmarkResult.item_id).where(
                BenchmarkResult.run_id.in_(run_ids),
                BenchmarkResult.item_id.in_(REFERENCE_ITEMS),
                BenchmarkResult.correct,
            )
        )
    ).all()
    found: dict[uuid.UUID, set[str]] = {run_id: set() for run_id in run_ids}
    for run_id, item_id in rows:
        found[run_id].add(item_id)
    return found


@router.get("")
async def overview(
    session: Session, services: Services, user: AuthenticatedUser
) -> BenchmarkOverview:
    stored = await latest_completed(session)
    correct = await _correct_reference_items(session, [run.id for run in stored])
    runs = [_run_out(run, correct[run.id]) for run in stored]
    runs.sort(key=lambda r: (-r.summary.accuracy, r.summary.latency_p95_ms))
    settings = services.settings
    return BenchmarkOverview(
        runs=runs,
        selected=select_default(
            {r.config.name: r.summary for r in runs}, {r.config.name for r in runs if r.eligible}
        ),
        selection_margin=SELECTION_MARGIN,
        reference_items=list(REFERENCE_ITEMS),
        serving=ServingModel(
            model=settings.ollama.llm_model,
            nodes={k: v for k, v in settings.agent.models.routing().items() if v},
            think=settings.ollama.think,
        ),
    )


@router.get("/runs/{run_id}")
async def run_detail(
    run_id: uuid.UUID, session: Session, user: AuthenticatedUser
) -> BenchmarkRunDetail:
    run = await session.get(BenchmarkRun, run_id)
    if run is None or run.status != "completed":
        raise HTTPException(status.HTTP_404_NOT_FOUND, "benchmark run not found")
    rows = (
        await session.scalars(
            select(BenchmarkResult)
            .where(BenchmarkResult.run_id == run_id)
            .order_by(BenchmarkResult.item_id)
        )
    ).all()
    results = []
    for row in rows:
        detail = row.detail
        sql = detail.get("sql")
        repairs = detail.get("repairs")
        error = detail.get("error")
        results.append(
            BenchmarkResultOut(
                item_id=row.item_id,
                difficulty=row.difficulty,
                question=row.question,
                correct=row.correct,
                reason=row.reason,
                status=row.status,
                latency_ms=row.latency_ms,
                tokens=row.tokens,
                repairs=repairs if isinstance(repairs, int) else 0,
                sql=[s for s in sql if isinstance(s, str)] if isinstance(sql, list) else [],
                error=error if isinstance(error, str) else None,
            )
        )
    correct = {r.item_id for r in results if r.correct}
    return BenchmarkRunDetail(**_run_out(run, correct).model_dump(), results=results)
