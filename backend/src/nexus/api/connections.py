"""Connections: the configured data source, its tables and the state of its retrieval index.

Read-only in v1 (a single demo connection from the environment). Network details (host, port, user)
are returned to admins only.
"""

from __future__ import annotations

import datetime as dt

from fastapi import APIRouter
from pydantic import BaseModel
from sqlalchemy import func, select

from nexus.api.deps import AuthenticatedUser, Services, Session
from nexus.db.models import Role, SchemaDocument, VerifiedExample

router = APIRouter(prefix="/api/connections", tags=["connections"])


class TableOut(BaseModel):
    name: str
    comment: str
    columns: int
    row_estimate: int
    references: list[str]


class IndexStatus(BaseModel):
    embedding_model: str
    fingerprint: str | None
    documents: dict[str, int]
    verified_examples: int
    built_at: dt.datetime | None


class ConnectionOut(BaseModel):
    key: str
    dialect: str
    database: str
    schema_name: str
    read_only: bool
    as_of: dt.date
    host: str | None
    port: int | None
    user: str | None
    llm_model: str
    tables: list[TableOut]
    index: IndexStatus


@router.get("")
async def list_connections(
    user: AuthenticatedUser, session: Session, services: Services
) -> list[ConnectionOut]:
    source = services.source
    model = services.settings.ollama.embedding_model
    scope = (
        SchemaDocument.connection_key == source.key,
        SchemaDocument.embedding_model == model,
    )
    counts = await session.execute(
        select(SchemaDocument.doc_type, func.count())
        .where(*scope)
        .group_by(SchemaDocument.doc_type)
    )
    meta = (
        await session.execute(
            select(func.max(SchemaDocument.fingerprint), func.max(SchemaDocument.created_at)).where(
                *scope, SchemaDocument.doc_type != "example"
            )
        )
    ).one()
    examples = await session.scalar(
        select(func.count()).where(VerifiedExample.connection_key == source.key)
    )
    admin = user.role is Role.ADMIN
    return [
        ConnectionOut(
            key=source.key,
            dialect=source.dialect,
            database=source.database,
            schema_name=source.schema,
            read_only=True,
            as_of=source.as_of,
            host=source.host if admin else None,
            port=source.port if admin else None,
            user=source.user if admin else None,
            llm_model=services.settings.ollama.llm_model,
            tables=[
                TableOut(
                    name=t.name,
                    comment=t.comment,
                    columns=t.columns,
                    row_estimate=t.row_estimate,
                    references=list(t.foreign_keys),
                )
                for t in source.tables
            ],
            index=IndexStatus(
                embedding_model=model,
                fingerprint=meta[0],
                documents={doc_type: int(n) for doc_type, n in counts},
                verified_examples=examples or 0,
                built_at=meta[1],
            ),
        )
    ]
