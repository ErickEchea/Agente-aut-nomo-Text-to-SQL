"""Long-term memory persistence."""

from __future__ import annotations

import hashlib
import unicodedata
import uuid
from datetime import UTC, date, datetime
from typing import Any

import structlog
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.agent.state import HistoryTurn
from nexus.agent.temporal import ResolvedRange
from nexus.db.models import Feedback, QueryStat, Run, UserPreference, VerifiedExample
from nexus.rag.documents import Document, tables_in_sql
from nexus.rag.embeddings import Embedder
from nexus.rag.store import PgDocumentStore

logger = structlog.get_logger("nexus.memory")

HISTORY_TURNS = 5
PREFERENCE_KEYS = {"locale", "default_chart", "show_sql"}


def question_key(text: str) -> str:
    """Stable key for "the same question" regardless of case, accents and spacing."""
    decomposed = unicodedata.normalize("NFKD", text.lower())
    plain = "".join(c for c in decomposed if not unicodedata.combining(c))
    words = "".join(c if c.isalnum() else " " for c in plain).split()
    return hashlib.sha256(" ".join(words).encode()).hexdigest()


class DatabaseMemorySink:
    """The agent's ``MemorySink`` for one run (the ``remember`` node)."""

    def __init__(
        self, sessions: async_sessionmaker[AsyncSession], user_id: uuid.UUID, run_id: uuid.UUID
    ) -> None:
        self._sessions = sessions
        self._user_id = user_id
        self._run_id = run_id

    async def remember(self, *, question: str, standalone: str, status: str) -> None:
        if status != "answered":
            return
        key = question_key(standalone or question)
        statement = insert(QueryStat).values(
            user_id=self._user_id,
            question_key=key,
            question=standalone or question,
            times_asked=1,
            last_run_id=self._run_id,
            last_asked_at=datetime.now(UTC),
        )
        statement = statement.on_conflict_do_update(
            index_elements=[QueryStat.user_id, QueryStat.question_key],
            set_={
                "times_asked": QueryStat.times_asked + 1,
                "question": statement.excluded.question,
                "last_run_id": statement.excluded.last_run_id,
                "last_asked_at": statement.excluded.last_asked_at,
            },
        )
        async with self._sessions() as session, session.begin():
            await session.execute(statement)


def _ranges_from_result(result: dict[str, Any] | None) -> tuple[ResolvedRange, ...]:
    return tuple(
        ResolvedRange(
            item["expression"],
            date.fromisoformat(item["start"]),
            date.fromisoformat(item["end"]),
            item["grain"],
        )
        for item in (result or {}).get("time_ranges", [])
    )


async def load_history(session: AsyncSession, conversation_id: uuid.UUID) -> list[HistoryTurn]:
    """Last answered turns of a conversation, oldest first."""
    runs = (
        await session.scalars(
            select(Run)
            .where(Run.conversation_id == conversation_id, Run.status == "answered")
            .order_by(Run.created_at.desc())
            .limit(HISTORY_TURNS)
        )
    ).all()
    return [
        HistoryTurn(
            question=run.question,
            standalone=str((run.result or {}).get("standalone_question") or run.question),
            ranges=_ranges_from_result(run.result),
            answer=(run.answer or "")[:300],
        )
        for run in reversed(runs)
    ]


async def frequent_questions(
    session: AsyncSession, user_id: uuid.UUID, limit: int = 10
) -> list[QueryStat]:
    return list(
        (
            await session.scalars(
                select(QueryStat)
                .where(QueryStat.user_id == user_id)
                .order_by(QueryStat.times_asked.desc(), QueryStat.last_asked_at.desc())
                .limit(limit)
            )
        ).all()
    )


async def get_preferences(session: AsyncSession, user_id: uuid.UUID) -> dict[str, Any]:
    row = await session.get(UserPreference, user_id)
    return dict(row.data) if row else {}


async def update_preferences(
    session: AsyncSession, user_id: uuid.UUID, changes: dict[str, Any]
) -> dict[str, Any]:
    unknown = set(changes) - PREFERENCE_KEYS
    if unknown:
        raise ValueError(f"unknown preference keys: {sorted(unknown)}")
    row = await session.get(UserPreference, user_id)
    if row is None:
        row = UserPreference(user_id=user_id, data={})
        session.add(row)
    row.data = {**row.data, **changes}
    await session.flush()
    return dict(row.data)


class ExampleIndexer:
    """Turns confirmed answers into verified few-shot examples and indexes them for retrieval."""

    def __init__(self, store: PgDocumentStore, embedder: Embedder) -> None:
        self._store = store
        self._embedder = embedder

    async def add_from_run(
        self, session: AsyncSession, run: Run, user_id: uuid.UUID, *, dialect: str = "postgres"
    ) -> list[VerifiedExample]:
        """One example per answered step (question → validated SQL); idempotent per question and
        data source (the run's connection)."""
        connection_key = run.connection_key
        created: list[VerifiedExample] = []
        for step in (run.result or {}).get("results", []):
            question, sql = str(step["question"]), str(step["sql"])
            key = question_key(question)
            exists = await session.scalar(
                select(func.count())
                .select_from(VerifiedExample)
                .where(
                    VerifiedExample.connection_key == connection_key,
                    VerifiedExample.question_key == key,
                )
            )
            if exists:
                continue
            example = VerifiedExample(
                connection_key=connection_key,
                question=question,
                question_key=key,
                sql=sql,
                tables=list(tables_in_sql(sql, dialect=dialect)),
                created_by=user_id,
                run_id=run.id,
            )
            session.add(example)
            await session.flush()
            created.append(example)
        for example in created:
            doc = Document(
                "example",
                f"example:{example.id}",
                tuple(example.tables),
                "Pregunta verificada",
                example.question,
            )
            (vector,) = await self._embedder.embed_documents([(doc.title, doc.content)])
            await self._store.add(connection_key, self._embedder.profile.model, doc, vector)
        if created:
            logger.info("memory.examples_verified", count=len(created), run_id=str(run.id))
        return created


async def save_feedback(
    session: AsyncSession,
    *,
    run_id: uuid.UUID,
    user_id: uuid.UUID,
    rating: str,
    comment: str | None,
) -> Feedback:
    statement = (
        insert(Feedback)
        .values(run_id=run_id, user_id=user_id, rating=rating, comment=comment)
        .on_conflict_do_update(
            constraint="feedback_run_user_key", set_={"rating": rating, "comment": comment}
        )
        .returning(Feedback)
    )
    return (await session.execute(statement)).scalar_one()
