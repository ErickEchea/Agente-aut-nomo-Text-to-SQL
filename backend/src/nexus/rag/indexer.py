"""Build (or reuse) the retrieval index of a connection."""

from __future__ import annotations

import time
import uuid
from collections.abc import Sequence
from dataclasses import dataclass

import structlog
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.agent.catalog import SchemaCatalog
from nexus.agent.glossary import Glossary
from nexus.db.models import VerifiedExample
from nexus.rag.documents import Document, ExampleRecord, build_documents, fingerprint
from nexus.rag.embeddings import Embedder
from nexus.rag.retriever import RetrievedExample
from nexus.rag.store import PgDocumentStore

logger = structlog.get_logger("nexus.rag")


@dataclass(frozen=True, slots=True)
class IndexReport:
    rebuilt: bool
    documents: int
    seconds: float
    fingerprint: str


async def load_example_records(
    sessions: async_sessionmaker[AsyncSession], connection_key: str
) -> list[ExampleRecord]:
    async with sessions() as session:
        rows = await session.scalars(
            select(VerifiedExample)
            .where(VerifiedExample.connection_key == connection_key)
            .order_by(VerifiedExample.created_at)
        )
        return [ExampleRecord(str(r.id), r.question, r.sql, tuple(r.tables)) for r in rows]


def example_loader(sessions: async_sessionmaker[AsyncSession]):  # type: ignore[no-untyped-def]
    async def load(refs: Sequence[str]) -> list[RetrievedExample]:
        ids = [uuid.UUID(r.removeprefix("example:")) for r in refs if r.startswith("example:")]
        if not ids:
            return []
        async with sessions() as session:
            rows = {
                str(r.id): r
                for r in await session.scalars(
                    select(VerifiedExample).where(VerifiedExample.id.in_(ids))
                )
            }
        return [
            RetrievedExample(
                ref,
                rows[ref.removeprefix("example:")].question,
                rows[ref.removeprefix("example:")].sql,
            )
            for ref in refs
            if ref.removeprefix("example:") in rows
        ]

    return load


async def ensure_index(
    *,
    store: PgDocumentStore,
    embedder: Embedder,
    catalog: SchemaCatalog,
    glossary: Glossary,
    samples: dict[tuple[str, str], list[str]],
    examples: Sequence[ExampleRecord],
    connection_key: str,
    force: bool = False,
) -> IndexReport:
    started = time.perf_counter()
    docs: list[Document] = build_documents(catalog, glossary, samples, examples)
    model = embedder.profile.model
    print_ = fingerprint(
        docs, f"{model}|{embedder.profile.query_template}|{embedder.profile.document_template}"
    )
    if not force and await store.current_fingerprint(connection_key, model) == print_:
        return IndexReport(False, len(docs), time.perf_counter() - started, print_)
    vectors = await embedder.embed_documents([(d.title, d.content) for d in docs])
    await store.replace(connection_key, model, print_, docs, vectors)
    seconds = time.perf_counter() - started
    logger.info(
        "rag.indexed",
        connection=connection_key,
        model=model,
        documents=len(docs),
        seconds=round(seconds, 1),
    )
    return IndexReport(True, len(docs), seconds, print_)
