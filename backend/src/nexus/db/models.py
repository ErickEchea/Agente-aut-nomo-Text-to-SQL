"""App-database models (SQLAlchemy 2, typed). Schema changes go through Alembic migrations."""

from __future__ import annotations

import datetime as dt
import uuid
from enum import StrEnum
from typing import Any, ClassVar

from pgvector.sqlalchemy import Vector
from sqlalchemy import (
    BigInteger,
    Boolean,
    Date,
    DateTime,
    Enum,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.dialects.postgresql import ARRAY, JSONB, TSVECTOR, UUID
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    type_annotation_map: ClassVar[dict[Any, Any]] = {dict[str, Any]: JSONB, list[Any]: JSONB}


class Role(StrEnum):
    ADMIN = "admin"
    ANALYST = "analyst"
    VIEWER = "viewer"


def _uuid() -> uuid.UUID:
    return uuid.uuid4()


class TimestampMixin:
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class User(TimestampMixin, Base):
    __tablename__ = "users"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    email: Mapped[str] = mapped_column(String(320), unique=True, nullable=False)
    display_name: Mapped[str] = mapped_column(String(120), nullable=False)
    password_hash: Mapped[str] = mapped_column(Text, nullable=False)
    role: Mapped[Role] = mapped_column(
        Enum(Role, name="user_role", values_callable=lambda e: [m.value for m in e]), nullable=False
    )
    is_active: Mapped[bool] = mapped_column(Boolean, default=True, nullable=False)


class RefreshToken(TimestampMixin, Base):
    __tablename__ = "refresh_tokens"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    family_id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), index=True, nullable=False)
    token_hash: Mapped[str] = mapped_column(String(64), unique=True, nullable=False)
    expires_at: Mapped[dt.datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    used_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    revoked_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))


class Conversation(TimestampMixin, Base):
    __tablename__ = "conversations"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    # The data source this conversation asks (follow-ups stay on it).
    connection_key: Mapped[str] = mapped_column(
        String(80), nullable=False, server_default="retail-demo"
    )


class Run(TimestampMixin, Base):
    __tablename__ = "runs"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    conversation_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("conversations.id", ondelete="CASCADE"), index=True
    )
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    question: Mapped[str] = mapped_column(Text, nullable=False)
    connection_key: Mapped[str] = mapped_column(
        String(80), nullable=False, server_default="retail-demo"
    )
    status: Mapped[str] = mapped_column(String(20), nullable=False, default="running")
    answer: Mapped[str | None] = mapped_column(Text)
    result: Mapped[dict[str, Any] | None] = mapped_column(JSONB)
    prompt_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    completion_tokens: Mapped[int] = mapped_column(Integer, default=0, nullable=False)
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    finished_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))


class RunEvent(Base):
    __tablename__ = "run_events"
    __table_args__ = (UniqueConstraint("run_id", "seq", name="run_events_run_seq_key"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    run_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("runs.id", ondelete="CASCADE"), nullable=False
    )
    seq: Mapped[int] = mapped_column(Integer, nullable=False)
    event: Mapped[str] = mapped_column(String(40), nullable=False)
    data: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class AuditLog(Base):
    __tablename__ = "audit_log"
    __table_args__ = (Index("audit_log_created_idx", "created_at"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    user_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("users.id", ondelete="SET NULL"))
    run_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("runs.id", ondelete="SET NULL"))
    action: Mapped[str] = mapped_column(String(40), nullable=False)
    question: Mapped[str | None] = mapped_column(Text)
    sql: Mapped[str | None] = mapped_column(Text)
    outcome: Mapped[str] = mapped_column(String(20), nullable=False)
    row_count: Mapped[int | None] = mapped_column(Integer)
    duration_ms: Mapped[int | None] = mapped_column(Integer)
    error_code: Mapped[str | None] = mapped_column(String(40))
    client_ip: Mapped[str | None] = mapped_column(String(64))
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


# ------------------------------------------------------------------------------------------------
# Phase 3: schema RAG and memory
# ------------------------------------------------------------------------------------------------


class SchemaDocument(Base):
    """One retrievable unit about a data source: a table, a column, a glossary term or an example.

    ``embedding`` has no fixed dimension so indexes for different embedding models can coexist
    (ADR-0007 notes: per-connection document counts are small, so exact search is used).
    """

    __tablename__ = "schema_documents"
    __table_args__ = (
        Index("schema_documents_lookup_idx", "connection_key", "embedding_model"),
        Index("schema_documents_tsv_idx", "tsv", postgresql_using="gin"),
        Index(
            "schema_documents_ref_trgm_idx",
            "ref",
            postgresql_using="gin",
            postgresql_ops={"ref": "gin_trgm_ops"},
        ),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    connection_key: Mapped[str] = mapped_column(String(80), nullable=False)
    embedding_model: Mapped[str] = mapped_column(String(120), nullable=False)
    fingerprint: Mapped[str] = mapped_column(String(64), nullable=False)
    doc_type: Mapped[str] = mapped_column(String(20), nullable=False)
    ref: Mapped[str] = mapped_column(String(200), nullable=False)
    tables: Mapped[list[str]] = mapped_column(ARRAY(String(80)), nullable=False)
    content: Mapped[str] = mapped_column(Text, nullable=False)
    embedding: Mapped[Any] = mapped_column(Vector(), nullable=False)
    tsv: Mapped[Any] = mapped_column(TSVECTOR, nullable=False)
    created_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


class VerifiedExample(TimestampMixin, Base):
    """A question → SQL pair a user confirmed as correct; used as a few-shot example."""

    __tablename__ = "verified_examples"
    __table_args__ = (
        UniqueConstraint("connection_key", "question_key", name="verified_examples_question_key"),
    )

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    connection_key: Mapped[str] = mapped_column(String(80), nullable=False)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    question_key: Mapped[str] = mapped_column(String(64), nullable=False)
    sql: Mapped[str] = mapped_column(Text, nullable=False)
    tables: Mapped[list[str]] = mapped_column(ARRAY(String(80)), nullable=False)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    run_id: Mapped[uuid.UUID | None] = mapped_column(ForeignKey("runs.id", ondelete="SET NULL"))


class Feedback(TimestampMixin, Base):
    __tablename__ = "feedback"
    __table_args__ = (UniqueConstraint("run_id", "user_id", name="feedback_run_user_key"),)

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True, autoincrement=True)
    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"), index=True)
    user_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("users.id", ondelete="CASCADE"))
    rating: Mapped[str] = mapped_column(String(10), nullable=False)
    comment: Mapped[str | None] = mapped_column(Text)


class UserPreference(Base):
    __tablename__ = "user_preferences"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    data: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, default=dict)
    updated_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), onupdate=func.now(), nullable=False
    )


class QueryStat(Base):
    """Long-term memory of what each user asks (frequent questions)."""

    __tablename__ = "query_stats"

    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), primary_key=True
    )
    question_key: Mapped[str] = mapped_column(String(64), primary_key=True)
    question: Mapped[str] = mapped_column(Text, nullable=False)
    times_asked: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    last_run_id: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("runs.id", ondelete="SET NULL")
    )
    last_asked_at: Mapped[dt.datetime] = mapped_column(
        DateTime(timezone=True), server_default=func.now(), nullable=False
    )


# ------------------------------------------------------------------------------------------------
# Phase 4: dashboards
# ------------------------------------------------------------------------------------------------


class Dashboard(TimestampMixin, Base):
    __tablename__ = "dashboards"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    user_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("users.id", ondelete="CASCADE"), index=True
    )
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    # Shared dashboards are readable by every user (ADR-0010: viewers see shared dashboards).
    shared: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)


class DashboardItem(TimestampMixin, Base):
    """A pinned step of an answered run (its chart/KPI/table is rendered from the stored result)."""

    __tablename__ = "dashboard_items"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    dashboard_id: Mapped[uuid.UUID] = mapped_column(
        ForeignKey("dashboards.id", ondelete="CASCADE"), index=True
    )
    run_id: Mapped[uuid.UUID] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"))
    step: Mapped[int] = mapped_column(Integer, nullable=False)
    title: Mapped[str] = mapped_column(String(200), nullable=False)
    position: Mapped[int] = mapped_column(Integer, nullable=False, default=0)


# ------------------------------------------------------------------------------------------------
# Phase 5: registered data sources (ADR-0012, ADR-0013)
# ------------------------------------------------------------------------------------------------


class DataConnection(TimestampMixin, Base):
    """A database the agent may query. ``secret`` is Fernet-encrypted and never leaves the backend.

    The built-in demo source is configured from the environment and is not stored here.
    """

    __tablename__ = "data_connections"

    id: Mapped[uuid.UUID] = mapped_column(UUID(as_uuid=True), primary_key=True, default=_uuid)
    key: Mapped[str] = mapped_column(String(80), unique=True, nullable=False)
    name: Mapped[str] = mapped_column(String(120), nullable=False)
    kind: Mapped[str] = mapped_column(String(20), nullable=False)  # postgresql | mysql | sqlite
    host: Mapped[str | None] = mapped_column(String(255))
    port: Mapped[int | None] = mapped_column(Integer)
    database: Mapped[str] = mapped_column(String(255), nullable=False)  # name, or SQLite file
    username: Mapped[str | None] = mapped_column(String(120))
    secret: Mapped[str | None] = mapped_column(Text)
    schema_name: Mapped[str] = mapped_column(String(120), nullable=False)
    as_of: Mapped[dt.date | None] = mapped_column(Date)
    pii_columns: Mapped[str] = mapped_column(Text, nullable=False, default="")
    writable_acknowledged: Mapped[bool] = mapped_column(Boolean, nullable=False, default=False)
    created_by: Mapped[uuid.UUID | None] = mapped_column(
        ForeignKey("users.id", ondelete="SET NULL")
    )
    last_tested_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
    index_status: Mapped[str] = mapped_column(String(20), nullable=False, default="pending")
    index_error: Mapped[str | None] = mapped_column(Text)
    indexed_at: Mapped[dt.datetime | None] = mapped_column(DateTime(timezone=True))
