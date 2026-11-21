"""Dashboards: named boards of pinned run steps, rendered from the stored result.

Permissions follow ADR-0010: everyone reads their own and shared dashboards; only analysts and
admins create, edit, pin or unpin, and only the owner (or an admin) may change a dashboard. A
pinned item points to an answered run and one of its steps; finished runs are immutable, so the
pinned view never drifts.
"""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, Field
from sqlalchemy import func, or_, select

from nexus.agent.charts import ChartSpec
from nexus.api.deps import AuthenticatedUser, CurrentUser, Session, require_roles
from nexus.db.models import Dashboard, DashboardItem, Role, Run, User
from nexus.runs.schemas import RunResult, StepOut

router = APIRouter(prefix="/api/dashboards", tags=["dashboards"])

Contributor = Annotated[CurrentUser, Depends(require_roles(Role.ADMIN, Role.ANALYST))]

MAX_DASHBOARDS_PER_USER = 50
MAX_ITEMS_PER_DASHBOARD = 24


class DashboardCreate(BaseModel):
    name: str = Field(min_length=1, max_length=120)
    shared: bool = False


class DashboardUpdate(BaseModel):
    name: str | None = Field(default=None, min_length=1, max_length=120)
    shared: bool | None = None


class PinRequest(BaseModel):
    run_id: uuid.UUID
    step: int = Field(default=0, ge=0)
    title: str | None = Field(default=None, min_length=1, max_length=200)


class ItemOrder(BaseModel):
    item_ids: list[uuid.UUID] = Field(max_length=MAX_ITEMS_PER_DASHBOARD)


class DashboardSummary(BaseModel):
    id: uuid.UUID
    name: str
    shared: bool
    owner_name: str
    editable: bool
    item_count: int
    created_at: dt.datetime


class DashboardItemOut(BaseModel):
    id: uuid.UUID
    run_id: uuid.UUID
    step: int
    title: str
    position: int
    question: str
    result: StepOut | None = Field(description="None if the pinned step no longer exists")
    chart: ChartSpec | None
    created_at: dt.datetime


class DashboardOut(DashboardSummary):
    items: list[DashboardItemOut]


def _can_edit(dashboard: Dashboard, user: CurrentUser) -> bool:
    return user.role is not Role.VIEWER and (
        dashboard.user_id == user.id or user.role is Role.ADMIN
    )


async def _load(session: Session, dashboard_id: uuid.UUID, user: CurrentUser) -> Dashboard:
    dashboard = await session.get(Dashboard, dashboard_id)
    visible = dashboard is not None and (
        dashboard.shared or dashboard.user_id == user.id or user.role is Role.ADMIN
    )
    if dashboard is None or not visible:
        # Not found and not visible look the same: do not leak other users' private dashboards.
        raise HTTPException(status.HTTP_404_NOT_FOUND, "dashboard not found")
    return dashboard


async def _load_editable(session: Session, dashboard_id: uuid.UUID, user: CurrentUser) -> Dashboard:
    dashboard = await _load(session, dashboard_id, user)
    if not _can_edit(dashboard, user):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "only the owner can change this dashboard")
    return dashboard


async def _summary(session: Session, dashboard: Dashboard, user: CurrentUser) -> DashboardSummary:
    owner = await session.get(User, dashboard.user_id)
    count = await session.scalar(
        select(func.count()).where(DashboardItem.dashboard_id == dashboard.id)
    )
    return DashboardSummary(
        id=dashboard.id,
        name=dashboard.name,
        shared=dashboard.shared,
        owner_name=owner.display_name if owner else "",
        editable=_can_edit(dashboard, user),
        item_count=count or 0,
        created_at=dashboard.created_at,
    )


def _step_view(run: Run, step: int) -> tuple[StepOut | None, ChartSpec | None]:
    if run.result is None:
        return None, None
    result = RunResult.model_validate(run.result)
    step_out = next((s for s in result.results if s.index == step), None)
    chart = next((c for c in result.charts if c.step == step), None)
    return step_out, chart


async def _items(session: Session, dashboard: Dashboard) -> list[DashboardItemOut]:
    rows = await session.execute(
        select(DashboardItem, Run)
        .join(Run, Run.id == DashboardItem.run_id)
        .where(DashboardItem.dashboard_id == dashboard.id)
        .order_by(DashboardItem.position, DashboardItem.created_at)
    )
    items: list[DashboardItemOut] = []
    for item, run in rows:
        step_out, chart = _step_view(run, item.step)
        items.append(
            DashboardItemOut(
                id=item.id,
                run_id=item.run_id,
                step=item.step,
                title=item.title,
                position=item.position,
                question=run.question,
                result=step_out,
                chart=chart,
                created_at=item.created_at,
            )
        )
    return items


async def _full(session: Session, dashboard: Dashboard, user: CurrentUser) -> DashboardOut:
    summary = await _summary(session, dashboard, user)
    return DashboardOut(**summary.model_dump(), items=await _items(session, dashboard))


@router.get("")
async def list_dashboards(user: AuthenticatedUser, session: Session) -> list[DashboardSummary]:
    rows = await session.scalars(
        select(Dashboard)
        .where(or_(Dashboard.user_id == user.id, Dashboard.shared.is_(True)))
        .order_by(Dashboard.created_at.desc())
    )
    return [await _summary(session, d, user) for d in rows]


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_dashboard(
    body: DashboardCreate, user: Contributor, session: Session
) -> DashboardSummary:
    owned = await session.scalar(select(func.count()).where(Dashboard.user_id == user.id))
    if (owned or 0) >= MAX_DASHBOARDS_PER_USER:
        raise HTTPException(
            status.HTTP_409_CONFLICT, f"at most {MAX_DASHBOARDS_PER_USER} dashboards per user"
        )
    dashboard = Dashboard(user_id=user.id, name=body.name.strip(), shared=body.shared)
    session.add(dashboard)
    await session.commit()
    await session.refresh(dashboard)
    return await _summary(session, dashboard, user)


@router.get("/{dashboard_id}")
async def get_dashboard(
    dashboard_id: uuid.UUID, user: AuthenticatedUser, session: Session
) -> DashboardOut:
    return await _full(session, await _load(session, dashboard_id, user), user)


@router.patch("/{dashboard_id}")
async def update_dashboard(
    dashboard_id: uuid.UUID, body: DashboardUpdate, user: Contributor, session: Session
) -> DashboardSummary:
    dashboard = await _load_editable(session, dashboard_id, user)
    if body.name is not None:
        dashboard.name = body.name.strip()
    if body.shared is not None:
        dashboard.shared = body.shared
    await session.commit()
    return await _summary(session, dashboard, user)


@router.delete("/{dashboard_id}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_dashboard(
    dashboard_id: uuid.UUID, user: Contributor, session: Session
) -> Response:
    dashboard = await _load_editable(session, dashboard_id, user)
    await session.delete(dashboard)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.post("/{dashboard_id}/items", status_code=status.HTTP_201_CREATED)
async def pin_item(
    dashboard_id: uuid.UUID, body: PinRequest, user: Contributor, session: Session
) -> DashboardItemOut:
    dashboard = await _load_editable(session, dashboard_id, user)
    run = await session.get(Run, body.run_id)
    if run is None or (run.user_id != user.id and user.role is not Role.ADMIN):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "run not found")
    step_out, chart = _step_view(run, body.step) if run.status == "answered" else (None, None)
    if step_out is None:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, "only a step of an answered run can be pinned"
        )
    stats = (
        await session.execute(
            select(func.count(), func.coalesce(func.max(DashboardItem.position), -1)).where(
                DashboardItem.dashboard_id == dashboard.id
            )
        )
    ).one()
    count, last_position = int(stats[0]), int(stats[1])
    if count >= MAX_ITEMS_PER_DASHBOARD:
        raise HTTPException(
            status.HTTP_409_CONFLICT, f"at most {MAX_ITEMS_PER_DASHBOARD} items per dashboard"
        )
    item = DashboardItem(
        dashboard_id=dashboard.id,
        run_id=run.id,
        step=body.step,
        title=(body.title or step_out.question or run.question).strip()[:200],
        position=last_position + 1,
    )
    session.add(item)
    await session.commit()
    await session.refresh(item)
    return DashboardItemOut(
        id=item.id,
        run_id=run.id,
        step=item.step,
        title=item.title,
        position=item.position,
        question=run.question,
        result=step_out,
        chart=chart,
        created_at=item.created_at,
    )


@router.delete("/{dashboard_id}/items/{item_id}", status_code=status.HTTP_204_NO_CONTENT)
async def unpin_item(
    dashboard_id: uuid.UUID, item_id: uuid.UUID, user: Contributor, session: Session
) -> Response:
    dashboard = await _load_editable(session, dashboard_id, user)
    item = await session.get(DashboardItem, item_id)
    if item is None or item.dashboard_id != dashboard.id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "item not found")
    await session.delete(item)
    await session.commit()
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.put("/{dashboard_id}/items/order")
async def reorder_items(
    dashboard_id: uuid.UUID, body: ItemOrder, user: Contributor, session: Session
) -> DashboardOut:
    dashboard = await _load_editable(session, dashboard_id, user)
    items = {
        i.id: i
        for i in await session.scalars(
            select(DashboardItem).where(DashboardItem.dashboard_id == dashboard.id)
        )
    }
    if len(body.item_ids) != len(set(body.item_ids)) or set(body.item_ids) != set(items):
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            "item_ids must list every item of the dashboard exactly once",
        )
    for position, item_id in enumerate(body.item_ids):
        items[item_id].position = position
    await session.commit()
    return await _full(session, dashboard, user)
