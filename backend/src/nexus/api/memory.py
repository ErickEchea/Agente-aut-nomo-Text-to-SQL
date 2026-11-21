"""Memory endpoints: feedback (→ verified examples), preferences and frequent questions."""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Annotated, Any, Literal

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel, Field

from nexus.api.deps import AuthenticatedUser, CurrentUser, Services, Session, require_roles
from nexus.db.models import Role, Run
from nexus.memory.store import (
    frequent_questions,
    get_preferences,
    save_feedback,
    update_preferences,
)

router = APIRouter(tags=["memory"])

Contributor = Annotated[CurrentUser, Depends(require_roles(Role.ADMIN, Role.ANALYST))]


class FeedbackRequest(BaseModel):
    rating: Literal["up", "down"]
    comment: str | None = Field(default=None, max_length=1000)
    verify: bool = Field(
        default=False, description="Mark the answer's SQL as correct: it becomes a few-shot example"
    )


class FeedbackOut(BaseModel):
    rating: str
    comment: str | None
    verified_examples: int


class FrequentQuestion(BaseModel):
    question: str
    times_asked: int
    last_run_id: uuid.UUID | None
    last_asked_at: dt.datetime


class Preferences(BaseModel):
    locale: Literal["es", "en"] | None = None
    default_chart: Literal["auto", "bar", "line", "pie", "table"] | None = None
    show_sql: bool | None = None


@router.post("/api/runs/{run_id}/feedback")
async def give_feedback(
    run_id: uuid.UUID,
    body: FeedbackRequest,
    user: Contributor,
    session: Session,
    services: Services,
) -> FeedbackOut:
    run = await session.get(Run, run_id)
    if run is None or (run.user_id != user.id and user.role is not Role.ADMIN):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "run not found")
    if body.verify and (body.rating != "up" or run.status != "answered"):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "only answered runs rated 'up' can be verified"
        )
    await save_feedback(
        session, run_id=run.id, user_id=user.id, rating=body.rating, comment=body.comment
    )
    created = []
    if body.verify:
        source = await services.registry.get(run.connection_key)
        created = await services.examples.add_from_run(
            session, run, user.id, dialect=source.profile.sqlglot
        )
    await session.commit()
    return FeedbackOut(rating=body.rating, comment=body.comment, verified_examples=len(created))


@router.get("/api/memory/frequent")
async def list_frequent(user: AuthenticatedUser, session: Session) -> list[FrequentQuestion]:
    return [
        FrequentQuestion(
            question=q.question,
            times_asked=q.times_asked,
            last_run_id=q.last_run_id,
            last_asked_at=q.last_asked_at,
        )
        for q in await frequent_questions(session, user.id)
    ]


@router.get("/api/memory/preferences")
async def read_preferences(user: AuthenticatedUser, session: Session) -> dict[str, Any]:
    return await get_preferences(session, user.id)


@router.put("/api/memory/preferences")
async def write_preferences(
    body: Preferences, user: AuthenticatedUser, session: Session
) -> dict[str, Any]:
    data = await update_preferences(session, user.id, body.model_dump(exclude_none=True))
    await session.commit()
    return data
