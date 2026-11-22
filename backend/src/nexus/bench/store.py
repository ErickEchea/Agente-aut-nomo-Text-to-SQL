"""Persist benchmark runs in the app DB (for the Benchmark page) and as JSON in bench/results."""

from __future__ import annotations

import datetime as dt
import json
import uuid
from collections.abc import Sequence
from pathlib import Path

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.bench.metrics import Summary
from nexus.bench.runner import BenchConfig, ItemOutcome
from nexus.db.models import BenchmarkResult, BenchmarkRun


class RunRecord(BaseModel):
    """The JSON document written to bench/results/ (and the shape the report reads back)."""

    run_id: str
    config: BenchConfig
    subset: str
    dataset_version: str
    git_sha: str | None
    started_at: dt.datetime
    finished_at: dt.datetime
    summary: Summary
    outcomes: list[ItemOutcome]


async def start_run(
    sessions: async_sessionmaker[AsyncSession],
    config: BenchConfig,
    *,
    subset: str,
    dataset_version: str,
    git_sha: str | None,
) -> uuid.UUID:
    async with sessions() as session, session.begin():
        run = BenchmarkRun(
            config_name=config.name,
            config=config.model_dump(mode="json"),
            subset=subset,
            status="running",
            dataset_version=dataset_version,
            git_sha=git_sha,
        )
        session.add(run)
        await session.flush()
        return run.id


async def finish_run(
    sessions: async_sessionmaker[AsyncSession],
    run_id: uuid.UUID,
    outcomes: Sequence[ItemOutcome],
    summary: Summary,
) -> None:
    async with sessions() as session, session.begin():
        run = await session.get(BenchmarkRun, run_id)
        if run is None:
            raise LookupError(f"benchmark run {run_id} not found")
        run.status = "completed"
        run.items = summary.items
        run.correct = summary.correct
        run.summary = summary.model_dump(mode="json")
        run.finished_at = dt.datetime.now(dt.UTC)
        session.add_all(
            BenchmarkResult(
                run_id=run_id,
                item_id=o.item_id,
                difficulty=o.difficulty,
                question=o.question,
                correct=o.correct,
                reason=o.reason[:40],
                status=o.status[:20],
                latency_ms=o.latency_ms,
                tokens=o.prompt_tokens + o.completion_tokens,
                detail=o.model_dump(
                    mode="json",
                    include={
                        "sql",
                        "error",
                        "nodes",
                        "repairs",
                        "sql_attempts",
                        "llm_calls",
                        "recall_at_5",
                        "context_complete",
                        "explanation_fallback",
                        "first_attempt_ok",
                        "prompt_tokens",
                        "completion_tokens",
                    },
                ),
            )
            for o in outcomes
        )


async def fail_run(
    sessions: async_sessionmaker[AsyncSession], run_id: uuid.UUID, error: str
) -> None:
    async with sessions() as session, session.begin():
        run = await session.get(BenchmarkRun, run_id)
        if run is not None:
            run.status = "failed"
            run.summary = {"error": error[:500]}
            run.finished_at = dt.datetime.now(dt.UTC)


async def latest_completed(session: AsyncSession, *, subset: str = "full") -> list[BenchmarkRun]:
    """The newest completed run of each configuration for a subset."""
    rows = (
        await session.scalars(
            select(BenchmarkRun)
            .where(BenchmarkRun.status == "completed", BenchmarkRun.subset == subset)
            .order_by(BenchmarkRun.finished_at.desc())
        )
    ).all()
    newest: dict[str, BenchmarkRun] = {}
    for run in rows:
        newest.setdefault(run.config_name, run)
    return list(newest.values())


def write_record(directory: Path, record: RunRecord) -> Path:
    directory.mkdir(parents=True, exist_ok=True)
    stamp = record.finished_at.strftime("%Y%m%dT%H%M%SZ")
    path = directory / f"{stamp}-{record.subset}-{record.config.name}.json"
    path.write_text(
        json.dumps(record.model_dump(mode="json"), ensure_ascii=False, indent=1) + "\n",
        encoding="utf-8",
    )
    return path


def read_records(directory: Path) -> list[RunRecord]:
    return [
        RunRecord.model_validate_json(path.read_text(encoding="utf-8"))
        for path in sorted(directory.glob("*.json"))
        if not path.name.startswith("retrieval")
    ]
