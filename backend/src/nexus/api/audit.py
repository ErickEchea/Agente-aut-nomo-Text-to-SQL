"""Audit log (admin only)."""

from __future__ import annotations

import datetime as dt
import uuid
from typing import Annotated

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import select

from nexus.api.deps import CurrentUser, Session, require_roles
from nexus.db.models import AuditLog, Role

router = APIRouter(prefix="/api/audit", tags=["audit"])

AdminUser = Annotated[CurrentUser, Depends(require_roles(Role.ADMIN))]


class AuditEntry(BaseModel):
    id: int
    created_at: dt.datetime
    user_id: uuid.UUID | None
    run_id: uuid.UUID | None
    action: str
    question: str | None
    sql: str | None
    outcome: str
    row_count: int | None
    duration_ms: int | None
    error_code: str | None
    client_ip: str | None


@router.get("")
async def list_audit(
    _: AdminUser,
    session: Session,
    limit: int = Query(default=50, ge=1, le=500),
    before_id: int | None = Query(default=None, ge=1),
    outcome: str | None = Query(default=None, max_length=20),
) -> list[AuditEntry]:
    query = select(AuditLog).order_by(AuditLog.id.desc()).limit(limit)
    if before_id is not None:
        query = query.where(AuditLog.id < before_id)
    if outcome is not None:
        query = query.where(AuditLog.outcome == outcome)
    rows = await session.scalars(query)
    return [
        AuditEntry(
            id=r.id,
            created_at=r.created_at,
            user_id=r.user_id,
            run_id=r.run_id,
            action=r.action,
            question=r.question,
            sql=r.sql,
            outcome=r.outcome,
            row_count=r.row_count,
            duration_ms=r.duration_ms,
            error_code=r.error_code,
            client_ip=r.client_ip,
        )
        for r in rows
    ]
