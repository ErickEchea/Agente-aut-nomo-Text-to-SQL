"""Event persistence + in-process fan-out. Events are written before they are published, so a
reconnecting client can replay from ``Last-Event-ID`` without gaps."""

from __future__ import annotations

import asyncio
import uuid
from collections import defaultdict
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.db.models import RunEvent

TERMINAL_EVENT = "run.completed"


@dataclass(frozen=True, slots=True)
class StreamEvent:
    seq: int
    event: str
    data: dict[str, object]


class EventBroker:
    """Per-run subscriber queues (single process; swap for LISTEN/NOTIFY to scale out)."""

    def __init__(self) -> None:
        self._subscribers: dict[uuid.UUID, set[asyncio.Queue[StreamEvent]]] = defaultdict(set)

    def subscribe(self, run_id: uuid.UUID) -> asyncio.Queue[StreamEvent]:
        queue: asyncio.Queue[StreamEvent] = asyncio.Queue()
        self._subscribers[run_id].add(queue)
        return queue

    def unsubscribe(self, run_id: uuid.UUID, queue: asyncio.Queue[StreamEvent]) -> None:
        subscribers = self._subscribers.get(run_id)
        if subscribers is not None:
            subscribers.discard(queue)
            if not subscribers:
                self._subscribers.pop(run_id, None)

    def publish(self, run_id: uuid.UUID, event: StreamEvent) -> None:
        for queue in list(self._subscribers.get(run_id, ())):
            queue.put_nowait(event)


class PersistentEventSink:
    """The agent's ``EventSink`` for one run."""

    def __init__(
        self, run_id: uuid.UUID, sessions: async_sessionmaker[AsyncSession], broker: EventBroker
    ) -> None:
        self._run_id = run_id
        self._sessions = sessions
        self._broker = broker
        self._seq = 0
        self._lock = asyncio.Lock()

    async def emit(self, event: str, data: dict[str, object]) -> None:
        async with self._lock:  # strictly increasing seq even if nodes ever emit concurrently
            self._seq += 1
            payload = {**data, "ts": datetime.now(UTC).isoformat()}
            async with self._sessions() as session, session.begin():
                session.add(RunEvent(run_id=self._run_id, seq=self._seq, event=event, data=payload))
            self._broker.publish(self._run_id, StreamEvent(self._seq, event, payload))
