"""Agent runs: start (202), stream events (SSE with Last-Event-ID replay), inspect, cancel, list."""

from __future__ import annotations

import datetime as dt
import json
import uuid
from collections.abc import AsyncIterator
from typing import Any

from fastapi import APIRouter, HTTPException, Query, Request, status
from pydantic import BaseModel, Field
from sqlalchemy import select
from sse_starlette import EventSourceResponse, ServerSentEvent

from nexus.api.deps import (
    AuthenticatedUser,
    CurrentUser,
    Services,
    Session,
    client_ip,
    enforce_rate_limit,
)
from nexus.db.models import Role, Run, RunEvent
from nexus.runs.events import TERMINAL_EVENT
from nexus.runs.manager import ConcurrentRunError
from nexus.runs.schemas import RunResult

router = APIRouter(prefix="/api/runs", tags=["runs"])


class RunRequest(BaseModel):
    question: str = Field(min_length=3, max_length=1000)
    conversation_id: uuid.UUID | None = None


class RunCreated(BaseModel):
    run_id: uuid.UUID
    conversation_id: uuid.UUID
    events_url: str


class RunOut(BaseModel):
    id: uuid.UUID
    conversation_id: uuid.UUID
    question: str
    status: str
    answer: str | None
    result: RunResult | None
    prompt_tokens: int
    completion_tokens: int
    duration_ms: int | None
    created_at: dt.datetime
    finished_at: dt.datetime | None


class RunSummary(BaseModel):
    id: uuid.UUID
    conversation_id: uuid.UUID
    question: str
    status: str
    created_at: dt.datetime
    duration_ms: int | None


async def _load_run(session: Session, run_id: uuid.UUID, user: CurrentUser) -> Run:
    run = await session.get(Run, run_id)
    # Not found and not yours look the same: do not leak the existence of other users' runs.
    if run is None or (run.user_id != user.id and user.role is not Role.ADMIN):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "run not found")
    return run


@router.post("", status_code=status.HTTP_202_ACCEPTED)
async def start_run(
    body: RunRequest, request: Request, user: AuthenticatedUser, services: Services
) -> RunCreated:
    enforce_rate_limit(services, "runs", str(user.id))
    try:
        started = await services.runs.start(
            user_id=user.id,
            question=body.question.strip(),
            conversation_id=body.conversation_id,
            client_ip=client_ip(request),
        )
    except ConcurrentRunError as exc:
        raise HTTPException(
            status.HTTP_409_CONFLICT, f"another run is in progress: {exc}"
        ) from None
    return RunCreated(
        run_id=started.run_id,
        conversation_id=started.conversation_id,
        events_url=f"/api/runs/{started.run_id}/events",
    )


@router.get("")
async def list_runs(
    user: AuthenticatedUser, session: Session, limit: int = Query(default=20, ge=1, le=100)
) -> list[RunSummary]:
    rows = await session.scalars(
        select(Run).where(Run.user_id == user.id).order_by(Run.created_at.desc()).limit(limit)
    )
    return [
        RunSummary(
            id=r.id,
            conversation_id=r.conversation_id,
            question=r.question,
            status=r.status,
            created_at=r.created_at,
            duration_ms=r.duration_ms,
        )
        for r in rows
    ]


@router.get("/{run_id}")
async def get_run(run_id: uuid.UUID, user: AuthenticatedUser, session: Session) -> RunOut:
    run = await _load_run(session, run_id, user)
    return RunOut(
        id=run.id,
        conversation_id=run.conversation_id,
        question=run.question,
        status=run.status,
        answer=run.answer,
        result=RunResult.model_validate(run.result) if run.result else None,
        prompt_tokens=run.prompt_tokens,
        completion_tokens=run.completion_tokens,
        duration_ms=run.duration_ms,
        created_at=run.created_at,
        finished_at=run.finished_at,
    )


@router.delete("/{run_id}", status_code=status.HTTP_202_ACCEPTED)
async def cancel_run(
    run_id: uuid.UUID, user: AuthenticatedUser, session: Session, services: Services
) -> dict[str, bool]:
    await _load_run(session, run_id, user)
    return {"cancelled": await services.runs.cancel(run_id)}


def _sse(seq: int, event: str, data: dict[str, Any]) -> ServerSentEvent:
    return ServerSentEvent(
        json.dumps(data, ensure_ascii=False, default=str), event=event, id=str(seq)
    )


@router.get("/{run_id}/events")
async def stream_events(
    run_id: uuid.UUID,
    *,
    request: Request,
    user: AuthenticatedUser,
    session: Session,
    services: Services,
    last_event_id: int | None = Query(default=None, ge=0),
) -> EventSourceResponse:
    await _load_run(session, run_id, user)
    header = request.headers.get("last-event-id", "")
    after = last_event_id if last_event_id is not None else (int(header) if header.isdigit() else 0)

    async def events() -> AsyncIterator[ServerSentEvent]:
        # Subscribe before replaying so nothing published in between is lost (dedup by seq).
        queue = services.runs.broker.subscribe(run_id)
        sent = after
        try:
            async with services.sessions() as replay_session:
                stored = await replay_session.scalars(
                    select(RunEvent)
                    .where(RunEvent.run_id == run_id, RunEvent.seq > after)
                    .order_by(RunEvent.seq)
                )
                for row in stored:
                    yield _sse(row.seq, row.event, row.data)
                    sent = row.seq
                    if row.event == TERMINAL_EVENT:
                        return
            if not services.runs.is_running(run_id):
                return
            while True:
                event = await queue.get()
                if event.seq <= sent:
                    continue
                yield _sse(event.seq, event.event, event.data)
                sent = event.seq
                if event.event == TERMINAL_EVENT:
                    return
        finally:
            services.runs.broker.unsubscribe(run_id, queue)

    return EventSourceResponse(events(), ping=15, headers={"X-Accel-Buffering": "no"})
