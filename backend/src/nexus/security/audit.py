"""Audit log of every query the agent tried to run (validated, rejected or failed)."""

from __future__ import annotations

import uuid

import structlog
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.db.models import AuditLog

logger = structlog.get_logger("nexus.audit")


class DatabaseAuditSink:
    """The agent's ``AuditSink``: one row per SQL attempt; never raises into the agent."""

    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        *,
        user_id: uuid.UUID | None,
        run_id: uuid.UUID | None,
        client_ip: str | None,
    ) -> None:
        self._sessions = sessions
        self._user_id = user_id
        self._run_id = run_id
        self._client_ip = client_ip

    async def record(
        self,
        *,
        question: str,
        sql: str,
        outcome: str,
        row_count: int | None,
        duration_ms: float | None,
        error_code: str | None,
    ) -> None:
        entry = AuditLog(
            user_id=self._user_id,
            run_id=self._run_id,
            action="query",
            question=question,
            sql=sql,
            outcome=outcome,
            row_count=row_count,
            duration_ms=round(duration_ms) if duration_ms is not None else None,
            error_code=error_code,
            client_ip=self._client_ip,
        )
        try:
            async with self._sessions() as session, session.begin():
                session.add(entry)
        except Exception:  # an audit outage must be visible, but must not crash the answer
            logger.exception("audit.write_failed", run_id=str(self._run_id), outcome=outcome)
        logger.info(
            "audit.query",
            run_id=str(self._run_id),
            user_id=str(self._user_id),
            outcome=outcome,
            row_count=row_count,
            error_code=error_code,
        )
