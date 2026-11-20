"""Starts agent runs in the background, records their outcome and supports cancellation."""

from __future__ import annotations

import asyncio
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime

import structlog
from langgraph.graph.state import CompiledStateGraph
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.agent.graph import run_agent
from nexus.agent.state import AgentContext, AgentState, AuditSink, EventSink
from nexus.db.models import Conversation, Run
from nexus.llm import LLMError
from nexus.runs.events import TERMINAL_EVENT, EventBroker, PersistentEventSink
from nexus.runs.serialize import serialize_final
from nexus.security.audit import DatabaseAuditSink

logger = structlog.get_logger("nexus.runs")

ContextFactory = Callable[[EventSink, AuditSink], AgentContext]
HISTORY_TURNS = 5


class ConcurrentRunError(Exception):
    """The user already has a run in progress."""


@dataclass(frozen=True, slots=True)
class StartedRun:
    run_id: uuid.UUID
    conversation_id: uuid.UUID


class RunManager:
    def __init__(
        self,
        sessions: async_sessionmaker[AsyncSession],
        graph: CompiledStateGraph[AgentState, AgentContext, AgentState, AgentState],
        context_factory: ContextFactory,
        broker: EventBroker,
    ) -> None:
        self._sessions = sessions
        self._graph = graph
        self._context_factory = context_factory
        self.broker = broker
        self._tasks: dict[uuid.UUID, asyncio.Task[None]] = {}
        self._active_by_user: dict[uuid.UUID, uuid.UUID] = {}

    async def start(
        self,
        *,
        user_id: uuid.UUID,
        question: str,
        conversation_id: uuid.UUID | None,
        client_ip: str | None,
    ) -> StartedRun:
        if user_id in self._active_by_user:
            raise ConcurrentRunError(str(self._active_by_user[user_id]))
        async with self._sessions() as session, session.begin():
            conversation = None
            if conversation_id is not None:
                conversation = await session.get(Conversation, conversation_id)
                if conversation is None or conversation.user_id != user_id:
                    conversation = None
            if conversation is None:
                conversation = Conversation(user_id=user_id, title=question[:200])
                session.add(conversation)
                await session.flush()
            history = list(
                (
                    await session.scalars(
                        select(Run.question)
                        .where(Run.conversation_id == conversation.id)
                        .order_by(Run.created_at.desc())
                        .limit(HISTORY_TURNS)
                    )
                ).all()
            )[::-1]
            run = Run(conversation_id=conversation.id, user_id=user_id, question=question)
            session.add(run)
            await session.flush()
            started = StartedRun(run.id, conversation.id)

        self._active_by_user[user_id] = started.run_id
        task = asyncio.create_task(
            self._execute(started.run_id, user_id, question, history, client_ip),
            name=f"run-{started.run_id}",
        )
        self._tasks[started.run_id] = task
        task.add_done_callback(lambda _: self._finish(started.run_id, user_id))
        return started

    def _finish(self, run_id: uuid.UUID, user_id: uuid.UUID) -> None:
        self._tasks.pop(run_id, None)
        if self._active_by_user.get(user_id) == run_id:
            self._active_by_user.pop(user_id, None)

    def is_running(self, run_id: uuid.UUID) -> bool:
        return run_id in self._tasks

    async def cancel(self, run_id: uuid.UUID) -> bool:
        task = self._tasks.get(run_id)
        if task is None:
            return False
        task.cancel()
        return True

    async def _execute(
        self,
        run_id: uuid.UUID,
        user_id: uuid.UUID,
        question: str,
        history: list[str],
        client_ip: str | None,
    ) -> None:
        sink = PersistentEventSink(run_id, self._sessions, self.broker)
        audit = DatabaseAuditSink(
            self._sessions, user_id=user_id, run_id=run_id, client_ip=client_ip
        )
        ctx = self._context_factory(sink, audit)
        started = time.perf_counter()
        structlog.contextvars.bind_contextvars(run_id=str(run_id))
        await sink.emit("run.started", {"run_id": str(run_id), "question": question})
        try:
            final = await run_agent(
                self._graph, ctx, run_id=str(run_id), question=question, history=history
            )
            result = serialize_final(final)
        except asyncio.CancelledError:
            result = {"status": "cancelled", "answer": "Consulta cancelada."}
            await self._complete(run_id, sink, result, started)
            raise
        except LLMError as exc:
            logger.warning("runs.llm_unavailable", error=str(exc))
            result = {
                "status": "failed",
                "answer": (
                    "El servicio de modelos no está disponible en este momento. "
                    "Intenta de nuevo en unos minutos."
                ),
            }
        except Exception:
            logger.exception("runs.unexpected_error")
            result = {
                "status": "failed",
                "answer": "Ocurrió un error interno. El equipo puede revisarlo en el log.",
            }
        await self._complete(run_id, sink, result, started)

    async def _complete(
        self,
        run_id: uuid.UUID,
        sink: PersistentEventSink,
        result: dict[str, object],
        started: float,
    ) -> None:
        duration = round((time.perf_counter() - started) * 1000)
        raw_tokens = result.get("tokens")
        tokens: dict[str, object] = raw_tokens if isinstance(raw_tokens, dict) else {}
        async with self._sessions() as session, session.begin():
            run = await session.get(Run, run_id)
            if run is not None:
                run.status = str(result["status"])
                run.answer = str(result.get("answer", ""))
                run.result = result
                run.duration_ms = duration
                run.prompt_tokens = int(str(tokens.get("prompt", 0)))
                run.completion_tokens = int(str(tokens.get("completion", 0)))
                run.finished_at = datetime.now(UTC)
        await sink.emit(
            TERMINAL_EVENT,
            {
                "run_id": str(run_id),
                "status": result["status"],
                "answer": result.get("answer", ""),
                "duration_ms": duration,
            },
        )
        logger.info("runs.completed", status=result["status"], duration_ms=duration)

    async def shutdown(self) -> None:
        for task in list(self._tasks.values()):
            task.cancel()
        await asyncio.gather(*self._tasks.values(), return_exceptions=True)
