"""pgvector + full-text + trigram search over ``schema_documents``."""

from __future__ import annotations

import uuid
from collections.abc import Sequence
from dataclasses import dataclass

from sqlalchemy import Float, bindparam, cast, delete, func, literal, select, text
from sqlalchemy.dialects.postgresql import REGCONFIG
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.db.models import SchemaDocument
from nexus.rag.documents import Document

TS_CONFIG = "spanish"

# Lexemes are OR-ed: plainto_tsquery ANDs every word, which is far too strict for questions.
_LEXICAL_SQL = text(
    """
    SELECT d.doc_type, d.ref, d.tables, d.content, ts_rank_cd(d.tsv, q.query)::float AS score
    FROM schema_documents AS d,
         LATERAL (
             SELECT replace(
                 plainto_tsquery('spanish', unaccent(:question))::text, '&', '|'
             )::tsquery AS query
         ) AS q
    WHERE d.connection_key = :ck AND d.embedding_model = :model AND d.tsv @@ q.query
    ORDER BY score DESC
    LIMIT :k
    """
)


@dataclass(frozen=True, slots=True)
class Hit:
    doc_type: str
    ref: str
    tables: tuple[str, ...]
    content: str
    score: float  # higher is better within one ranking


def _lexical_vector(content: str) -> object:
    return func.to_tsvector(cast(literal(TS_CONFIG), REGCONFIG), func.unaccent(content))


class PgDocumentStore:
    def __init__(self, sessions: async_sessionmaker[AsyncSession]) -> None:
        self._sessions = sessions

    async def current_fingerprint(self, connection_key: str, model: str) -> str | None:
        async with self._sessions() as session:
            value = await session.scalar(
                select(SchemaDocument.fingerprint)
                .where(
                    SchemaDocument.connection_key == connection_key,
                    SchemaDocument.embedding_model == model,
                )
                .limit(1)
            )
        return str(value) if value is not None else None

    async def replace(
        self,
        connection_key: str,
        model: str,
        fingerprint: str,
        docs: Sequence[Document],
        vectors: Sequence[Sequence[float]],
    ) -> int:
        if len(docs) != len(vectors):
            raise ValueError("one vector per document is required")
        async with self._sessions() as session, session.begin():
            await session.execute(
                delete(SchemaDocument).where(
                    SchemaDocument.connection_key == connection_key,
                    SchemaDocument.embedding_model == model,
                )
            )
            for doc, vector in zip(docs, vectors, strict=True):
                session.add(self._row(connection_key, model, fingerprint, doc, vector))
        return len(docs)

    async def add(
        self, connection_key: str, model: str, doc: Document, vector: Sequence[float]
    ) -> None:
        """Append one document (e.g. a newly verified example) to an existing index."""
        current = await self.current_fingerprint(connection_key, model) or "incremental"
        async with self._sessions() as session, session.begin():
            session.add(self._row(connection_key, model, current, doc, vector))

    @staticmethod
    def _row(
        connection_key: str, model: str, fingerprint: str, doc: Document, vector: Sequence[float]
    ) -> SchemaDocument:
        return SchemaDocument(
            id=uuid.uuid4(),
            connection_key=connection_key,
            embedding_model=model,
            fingerprint=fingerprint,
            doc_type=doc.doc_type,
            ref=doc.ref,
            tables=list(doc.tables),
            content=doc.content,
            embedding=list(vector),
            tsv=_lexical_vector(doc.content),
        )

    def _scope(self, connection_key: str, model: str) -> list[object]:
        return [
            SchemaDocument.connection_key == connection_key,
            SchemaDocument.embedding_model == model,
        ]

    @staticmethod
    def _hits(rows: Sequence[object]) -> list[Hit]:
        return [
            Hit(r.doc_type, r.ref, tuple(r.tables), r.content, float(r.score))  # type: ignore[attr-defined]
            for r in rows
        ]

    async def dense(
        self, connection_key: str, model: str, vector: Sequence[float], k: int
    ) -> list[Hit]:
        distance = SchemaDocument.embedding.cosine_distance(list(vector))
        query = (
            select(
                SchemaDocument.doc_type,
                SchemaDocument.ref,
                SchemaDocument.tables,
                SchemaDocument.content,
                (1 - distance).label("score"),
            )
            .where(*self._scope(connection_key, model))  # type: ignore[arg-type]
            .order_by(distance)
            .limit(k)
        )
        async with self._sessions() as session:
            return self._hits((await session.execute(query)).all())

    async def lexical(self, connection_key: str, model: str, question: str, k: int) -> list[Hit]:
        async with self._sessions() as session:
            rows = await session.execute(
                _LEXICAL_SQL, {"question": question, "ck": connection_key, "model": model, "k": k}
            )
            return self._hits(rows.all())

    async def fuzzy(self, connection_key: str, model: str, question: str, k: int) -> list[Hit]:
        """Identifier-level trigram matching: catches typos and abbreviations ("sucursl")."""
        similarity = func.word_similarity(SchemaDocument.ref, bindparam("q", question))
        query = (
            select(
                SchemaDocument.doc_type,
                SchemaDocument.ref,
                SchemaDocument.tables,
                SchemaDocument.content,
                cast(similarity, Float).label("score"),
            )
            .where(
                *self._scope(connection_key, model),  # type: ignore[arg-type]
                SchemaDocument.doc_type.in_(("table", "column")),
                similarity > 0.45,
            )
            .order_by(similarity.desc())
            .limit(k)
        )
        async with self._sessions() as session:
            return self._hits((await session.execute(query)).all())
