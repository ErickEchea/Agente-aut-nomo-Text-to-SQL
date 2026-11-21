"""Data sources: the built-in demo plus connections admins register (ADR-0012, ADR-0013).

- Everyone can list sources and see their tables (to choose what to ask).
- Admins test, register, re-index and delete connections. Secrets are encrypted at rest and never
  returned; network details (host, port, user) are shown to admins only.
- A connection whose credentials could write is rejected unless the admin acknowledges it (the AST
  validator and read-only transactions still apply; the UI shows a warning badge).
"""

from __future__ import annotations

import asyncio
import datetime as dt
import re
import unicodedata
from typing import Annotated, Literal

import structlog
from fastapi import APIRouter, Depends, HTTPException, Response, status
from pydantic import BaseModel, Field, SecretStr, model_validator
from sqlalchemy import func, select

from nexus.api.deps import AuthenticatedUser, CurrentUser, Services, Session, require_roles
from nexus.datasources.dialects import Kind, profile_for
from nexus.datasources.registry import (
    KEY_PATTERN,
    ConnectionSpec,
    ProbeResult,
    SourceError,
    probe,
)
from nexus.db.models import DataConnection, Role, SchemaDocument, VerifiedExample

router = APIRouter(prefix="/api/connections", tags=["connections"])
logger = structlog.get_logger("nexus.connections")

AdminUser = Annotated[CurrentUser, Depends(require_roles(Role.ADMIN))]
SQLITE_SUFFIXES = (".db", ".sqlite", ".sqlite3")
IndexState = Literal["ready", "pending", "indexing", "failed"]

# Background indexing tasks are kept referenced until they finish (asyncio only keeps weak refs).
_INDEXING: set[asyncio.Task[None]] = set()


class ConnectionIn(BaseModel):
    name: str = Field(min_length=2, max_length=120)
    key: str | None = Field(default=None, description="Slug; derived from the name when empty")
    kind: Kind
    host: str | None = Field(default=None, max_length=255)
    port: int | None = Field(default=None, ge=1, le=65535)
    database: str = Field(min_length=1, max_length=255, description="Database, or SQLite file")
    username: str | None = Field(default=None, max_length=120)
    password: SecretStr | None = None
    schema_name: str | None = Field(default=None, max_length=120)
    as_of: dt.date | None = None
    pii_columns: str = Field(default="", max_length=2000)
    acknowledge_writable: bool = False

    @model_validator(mode="after")
    def _network_fields(self) -> ConnectionIn:
        if self.kind != "sqlite" and (not self.host or not self.username):
            raise ValueError("host and username are required for PostgreSQL and MySQL")
        return self

    def resolved_schema(self) -> str:
        if self.kind == "sqlite":
            return "main"
        if self.kind == "mysql":
            return self.database
        return self.schema_name or "public"

    def spec(self, key: str) -> ConnectionSpec:
        return ConnectionSpec(
            key=key,
            name=self.name.strip(),
            kind=self.kind,
            database=self.database.strip(),
            schema=self.resolved_schema(),
            host=self.host,
            port=self.port or profile_for(self.kind).default_port,
            username=self.username,
            password=self.password,
            as_of=self.as_of,
            pii_columns=tuple(c.strip() for c in self.pii_columns.split(",") if c.strip()),
        )


class ProbeOut(BaseModel):
    ok: bool
    version: str | None
    tables: int
    writable: bool
    writable_reasons: list[str]
    error: str | None


class ConnectionSummary(BaseModel):
    key: str
    name: str
    kind: Kind
    engine: str
    database: str
    schema_name: str
    builtin: bool
    read_only: bool
    as_of: dt.date | None
    index_status: IndexState
    index_error: str | None
    indexed_at: dt.datetime | None
    host: str | None
    port: int | None
    user: str | None


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


class ConnectionDetail(ConnectionSummary):
    llm_model: str
    tables: list[TableOut]
    index: IndexStatus


def _probe_out(result: ProbeResult) -> ProbeOut:
    return ProbeOut(
        ok=result.ok,
        version=result.version,
        tables=result.tables,
        writable=result.writable,
        writable_reasons=list(result.writable_reasons),
        error=result.error,
    )


def _slug(text: str) -> str:
    plain = unicodedata.normalize("NFKD", text).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "-", plain).strip("-")[:64]


def _builtin_summary(spec: ConnectionSpec, admin: bool) -> ConnectionSummary:
    return ConnectionSummary(
        key=spec.key,
        name=spec.name,
        kind=spec.kind,
        engine=profile_for(spec.kind).label,
        database=spec.database,
        schema_name=spec.schema,
        builtin=True,
        read_only=True,
        as_of=spec.as_of,
        index_status="ready",
        index_error=None,
        indexed_at=None,
        host=spec.host if admin else None,
        port=spec.port if admin else None,
        user=spec.username if admin else None,
    )


def _row_summary(row: DataConnection, admin: bool) -> ConnectionSummary:
    profile = profile_for(row.kind)
    state: IndexState = (
        row.index_status
        if row.index_status in ("ready", "pending", "indexing", "failed")
        else "pending"  # type: ignore[assignment]
    )
    return ConnectionSummary(
        key=row.key,
        name=row.name,
        kind=profile.kind,
        engine=profile.label,
        database=row.database,
        schema_name=row.schema_name,
        builtin=False,
        read_only=not row.writable_acknowledged,
        as_of=row.as_of,
        index_status=state,
        index_error=row.index_error,
        indexed_at=row.indexed_at,
        host=row.host if admin else None,
        port=row.port if admin else None,
        user=row.username if admin else None,
    )


async def _row(session: Session, key: str) -> DataConnection:
    row = await session.scalar(select(DataConnection).where(DataConnection.key == key))
    if row is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "connection not found")
    return row


def _start_indexing(services: Services, key: str) -> None:
    async def run() -> None:
        try:
            report = await services.registry.index(key, force=True)
            logger.info("connections.indexed", key=key, documents=report.documents)
        except Exception as exc:  # recorded on the row by the registry; never crash the loop
            logger.warning("connections.index_failed", key=key, error=str(exc))

    task = asyncio.create_task(run(), name=f"index-{key}")
    _INDEXING.add(task)
    task.add_done_callback(_INDEXING.discard)


@router.get("")
async def list_connections(
    user: AuthenticatedUser, session: Session, services: Services
) -> list[ConnectionSummary]:
    admin = user.role is Role.ADMIN
    rows = await session.scalars(select(DataConnection).order_by(DataConnection.created_at))
    builtin = _builtin_summary(services.registry.builtin, admin)
    return [builtin, *(_row_summary(r, admin) for r in rows)]


@router.get("/sqlite-files")
async def sqlite_files(user: AdminUser, services: Services) -> list[str]:
    """SQLite files an admin may register (only from the configured directory)."""
    base = services.settings.connections.sqlite_dir
    if not base.is_dir():
        return []
    return sorted(
        p.relative_to(base).as_posix()
        for p in base.rglob("*")
        if p.is_file() and p.suffix.lower() in SQLITE_SUFFIXES
    )


@router.post("/test")
async def test_connection(body: ConnectionIn, user: AdminUser, services: Services) -> ProbeOut:
    return _probe_out(await probe(body.spec(body.key or "test"), services.settings))


@router.post("", status_code=status.HTTP_201_CREATED)
async def create_connection(
    body: ConnectionIn, user: AdminUser, session: Session, services: Services
) -> ConnectionSummary:
    registry = services.registry
    if registry.cipher is None:
        raise HTTPException(
            status.HTTP_503_SERVICE_UNAVAILABLE,
            "connection management is disabled: set NEXUS_CREDENTIALS_KEYS",
        )
    key = body.key or _slug(body.name)
    if not KEY_PATTERN.match(key) or key == registry.builtin.key:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, "invalid or reserved key")
    if await registry.exists(key):
        raise HTTPException(status.HTTP_409_CONFLICT, "a connection with this key exists")
    spec = body.spec(key)
    result = await probe(spec, services.settings)
    if not result.ok:
        raise HTTPException(status.HTTP_422_UNPROCESSABLE_CONTENT, result.error or "unreachable")
    if result.writable and not body.acknowledge_writable:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "these credentials can write: " + "; ".join(result.writable_reasons),
        )
    password = spec.password.get_secret_value() if spec.password else None
    row = DataConnection(
        key=key,
        name=spec.name,
        kind=spec.kind,
        host=spec.host,
        port=spec.port,
        database=spec.database,
        username=spec.username,
        secret=registry.cipher.encrypt(password) if password else None,
        schema_name=spec.schema,
        as_of=spec.as_of,
        pii_columns=",".join(spec.pii_columns),
        writable_acknowledged=result.writable,
        created_by=user.id,
        last_tested_at=dt.datetime.now(dt.UTC),
        index_status="indexing",
    )
    session.add(row)
    await session.commit()
    await session.refresh(row)
    logger.info("connections.created", key=key, kind=spec.kind, writable=result.writable)
    _start_indexing(services, key)
    return _row_summary(row, True)


@router.get("/{key}")
async def get_connection(
    key: str, user: AuthenticatedUser, session: Session, services: Services
) -> ConnectionDetail:
    admin = user.role is Role.ADMIN
    registry = services.registry
    row = None if key == registry.builtin.key else await _row(session, key)
    try:
        source = await registry.get(key)
    except SourceError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from None
    model = services.settings.ollama.embedding_model
    scope = (SchemaDocument.connection_key == key, SchemaDocument.embedding_model == model)
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
        select(func.count()).where(VerifiedExample.connection_key == key)
    )
    summary = _builtin_summary(source.spec, admin) if row is None else _row_summary(row, admin)
    return ConnectionDetail(
        **summary.model_dump(),
        llm_model=services.settings.ollama.llm_model,
        tables=[
            TableOut(
                name=t.name,
                comment=t.comment,
                columns=len(t.columns),
                row_estimate=source.rows.get(t.name, 0),
                references=sorted({fk.ref_table for fk in t.foreign_keys}),
            )
            for t in sorted(source.catalog.tables.values(), key=lambda t: t.name)
        ],
        index=IndexStatus(
            embedding_model=model,
            fingerprint=meta[0],
            documents={doc_type: int(n) for doc_type, n in counts},
            verified_examples=examples or 0,
            built_at=meta[1],
        ),
    )


@router.post("/{key}/index", status_code=status.HTTP_202_ACCEPTED)
async def reindex(
    key: str, user: AdminUser, session: Session, services: Services
) -> ConnectionSummary:
    registry = services.registry
    if key == registry.builtin.key:
        _start_indexing(services, key)
        return _builtin_summary(registry.builtin, True)
    row = await _row(session, key)
    row.index_status = "indexing"
    row.index_error = None
    await session.commit()
    await registry.evict(key)  # pick up schema changes
    _start_indexing(services, key)
    return _row_summary(row, True)


@router.delete("/{key}", status_code=status.HTTP_204_NO_CONTENT)
async def delete_connection(
    key: str, user: AdminUser, session: Session, services: Services
) -> Response:
    registry = services.registry
    if key == registry.builtin.key:
        raise HTTPException(status.HTTP_400_BAD_REQUEST, "the demo source cannot be deleted")
    row = await _row(session, key)
    await session.delete(row)
    await session.commit()
    await registry.evict(key)
    await registry.store.delete(key)
    logger.info("connections.deleted", key=key)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
