"""Data sources the agent can query: the built-in demo plus user-registered connections.

A :class:`SourceRuntime` bundles everything the agent needs for one source (engine, read-only
executor, catalog, validation policy, glossary, PII masker, retriever). Runtimes are built lazily
and cached; registering, editing or deleting a connection evicts its runtime and disposes its pool.
"""

from __future__ import annotations

import asyncio
import datetime as dt
import re
from collections import defaultdict
from dataclasses import dataclass, field
from pathlib import Path

import structlog
from pydantic import SecretStr
from sqlalchemy import URL, select, text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

from nexus.agent.catalog import SchemaCatalog
from nexus.agent.glossary import Glossary, load_glossary
from nexus.agent.state import AgentContext, AuditSink, EventSink, MemorySink, NodeModels
from nexus.config import Settings
from nexus.datasources.cipher import CredentialCipher
from nexus.datasources.dialects import DialectProfile, Kind, profile_for
from nexus.datasources.introspect import (
    collect_samples,
    existing_indexes,
    introspect_catalog,
    row_estimates,
)
from nexus.datasources.targets import target_problem
from nexus.db.engines import create_engine
from nexus.db.models import DataConnection
from nexus.llm import LLMProvider
from nexus.rag.embeddings import Embedder
from nexus.rag.indexer import IndexReport, ensure_index, example_loader, load_example_records
from nexus.rag.retriever import HybridRetriever
from nexus.rag.store import PgDocumentStore
from nexus.security.pii import PiiMasker
from nexus.sql.executor import ReadOnlyExecutor
from nexus.sql.validator import ValidationPolicy

logger = structlog.get_logger("nexus.datasources")

KEY_PATTERN = re.compile(r"^[a-z0-9][a-z0-9-]{1,62}[a-z0-9]$")


class SourceError(Exception):
    """A connection that cannot be opened, or a request that is not allowed (human message)."""


class UnknownSourceError(KeyError):
    pass


@dataclass(frozen=True, slots=True)
class ConnectionSpec:
    key: str
    name: str
    kind: Kind
    database: str  # database name, or the SQLite file name inside the SQLite directory
    schema: str
    host: str | None = None
    port: int | None = None
    username: str | None = None
    password: SecretStr | None = None
    as_of: dt.date | None = None
    pii_columns: tuple[str, ...] = ()
    builtin: bool = False


def resolve_sqlite(sqlite_dir: Path, name: str) -> Path:
    """Only files inside ``sqlite_dir`` (no traversal, no symlink escape)."""
    base = sqlite_dir.resolve()
    target = (base / name).resolve()
    if base != target.parent and base not in target.parents:
        raise SourceError("El archivo SQLite debe estar dentro del directorio de datos permitido.")
    if not target.is_file():
        raise SourceError(f"No existe el archivo SQLite «{name}» en el directorio de datos.")
    return target


def create_source_engine(spec: ConnectionSpec, settings: Settings) -> AsyncEngine:
    cfg = settings.connections
    password = spec.password.get_secret_value() if spec.password else None
    if spec.kind == "postgresql":
        url = URL.create(
            "postgresql+asyncpg",
            username=spec.username,
            password=password,
            host=spec.host,
            port=spec.port,
            database=spec.database,
        )
        return create_async_engine(
            url,
            pool_size=cfg.pool_size,
            max_overflow=0,
            pool_pre_ping=True,
            pool_recycle=1800,
            connect_args={
                "timeout": cfg.connect_timeout_s,
                "server_settings": {
                    "application_name": f"nexus-{spec.key}",
                    "default_transaction_read_only": "on",
                },
            },
        )
    if spec.kind == "mysql":
        url = URL.create(
            "mysql+aiomysql",
            username=spec.username,
            password=password,
            host=spec.host,
            port=spec.port,
            database=spec.database,
            query={"charset": "utf8mb4"},
        )
        return create_async_engine(
            url,
            pool_size=cfg.pool_size,
            max_overflow=0,
            pool_pre_ping=True,
            pool_recycle=1800,
            connect_args={
                "connect_timeout": int(cfg.connect_timeout_s),
                # Every session starts read-only (blocks DDL too); the executor sets it again.
                "init_command": "SET SESSION transaction_read_only = ON",
            },
        )
    path = resolve_sqlite(cfg.sqlite_dir, spec.database)
    # mode=ro: the file is opened read-only by SQLite itself (ADR-0013).
    return create_async_engine(f"sqlite+aiosqlite:///file:{path.as_posix()}?mode=ro&uri=true")


# ---- probing (test connection) --------------------------------------------------------------

_PG_PRIVILEGES = text(
    """
    SELECT r.rolsuper,
           has_database_privilege(current_database(), 'CREATE'),
           CASE WHEN EXISTS (SELECT 1 FROM pg_namespace WHERE nspname = :schema)
                THEN has_schema_privilege(:schema, 'CREATE') ELSE false END,
           EXISTS (
             SELECT 1 FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
             WHERE n.nspname = :schema AND c.relkind IN ('r', 'p')
               AND (has_table_privilege(c.oid, 'INSERT')
                    OR has_table_privilege(c.oid, 'UPDATE')
                    OR has_table_privilege(c.oid, 'DELETE')
                    OR has_table_privilege(c.oid, 'TRUNCATE'))
           )
    FROM pg_roles r WHERE r.rolname = current_user
    """
)
_MYSQL_WRITE_GRANT = re.compile(
    r"\b(ALL PRIVILEGES|INSERT|UPDATE|DELETE|CREATE|DROP|ALTER|INDEX|EXECUTE|FILE|SUPER|"
    r"GRANT OPTION|TRIGGER|EVENT|LOCK TABLES|RELOAD|SHUTDOWN)\b",
    re.IGNORECASE,
)


@dataclass(frozen=True, slots=True)
class ProbeResult:
    ok: bool
    version: str | None = None
    tables: int = 0
    writable: bool = False
    writable_reasons: tuple[str, ...] = ()
    error: str | None = None


async def _write_privileges(engine: AsyncEngine, kind: Kind, schema: str) -> list[str]:
    """Check what the credentials could write, from catalog privilege data (never by writing)."""
    if kind == "sqlite":
        return []  # opened with mode=ro
    async with engine.connect() as conn:
        if kind == "postgresql":
            row = (await conn.execute(_PG_PRIVILEGES, {"schema": schema})).one()
            reasons = []
            if row[0]:
                reasons.append("superuser")
            if row[1]:
                reasons.append("CREATE on the database")
            if row[2]:
                reasons.append(f"CREATE on schema {schema}")
            if row[3]:
                reasons.append(f"INSERT/UPDATE/DELETE/TRUNCATE on tables of {schema}")
            return reasons
        grants = [str(r[0]) for r in (await conn.execute(text("SHOW GRANTS"))).all()]
    return [g for g in grants if _MYSQL_WRITE_GRANT.search(g.split(" ON ", 1)[0])]


_VERSION_SQL: dict[Kind, str] = {
    "postgresql": "SHOW server_version",
    "mysql": "SELECT VERSION()",
    "sqlite": "SELECT sqlite_version()",
}


async def check_target(spec: ConnectionSpec, settings: Settings) -> None:
    """Refuse network targets that are NEXUS's own services or forbidden ranges (ADR-0023)."""
    if spec.builtin or spec.kind == "sqlite":
        return
    port = spec.port or profile_for(spec.kind).default_port or 0
    problem = await target_problem(spec.host or "", port, settings)
    if problem is not None:
        raise SourceError(problem)


async def probe(spec: ConnectionSpec, settings: Settings) -> ProbeResult:
    """Open, read the version, count visible tables and check write privileges."""
    try:
        await check_target(spec, settings)
        engine = create_source_engine(spec, settings)
    except SourceError as exc:
        return ProbeResult(ok=False, error=str(exc))
    try:
        async with engine.connect() as conn:
            version = str((await conn.execute(text(_VERSION_SQL[spec.kind]))).scalar_one())
        catalog = await introspect_catalog(engine, spec.kind, spec.schema)
        reasons = await _write_privileges(engine, spec.kind, spec.schema)
        return ProbeResult(
            ok=True,
            version=version,
            tables=len(catalog.tables),
            writable=bool(reasons),
            writable_reasons=tuple(reasons),
        )
    except Exception as exc:
        message = str(getattr(exc, "orig", None) or exc).splitlines()[0][:300]
        return ProbeResult(ok=False, error=message.split(">: ", 1)[-1])
    finally:
        await engine.dispose()


# ---- runtime --------------------------------------------------------------------------------


@dataclass(slots=True)
class SourceRuntime:
    spec: ConnectionSpec
    profile: DialectProfile
    engine: AsyncEngine
    executor: ReadOnlyExecutor
    catalog: SchemaCatalog
    policy: ValidationPolicy
    glossary: Glossary
    masker: PiiMasker
    retriever: HybridRetriever
    samples: dict[tuple[str, str], list[str]]
    as_of: dt.date
    rows: dict[str, int] = field(default_factory=dict)
    indexes: set[tuple[str, str]] = field(default_factory=set)

    @property
    def key(self) -> str:
        return self.spec.key

    def agent_context(
        self,
        *,
        llm: LLMProvider,
        events: EventSink,
        audit: AuditSink,
        memory: MemorySink,
        locale: str = "es",
        max_repairs: int = 3,
        models: NodeModels | None = None,
    ) -> AgentContext:
        """The agent's view of this source; the API and the benchmark build it the same way."""
        return AgentContext(
            llm=llm,
            catalog=self.catalog,
            glossary=self.glossary,
            policy=self.policy,
            executor=self.executor,
            as_of=self.as_of,
            events=events,
            audit=audit,
            masker=self.masker,
            retriever=self.retriever,
            memory=memory,
            models=models or NodeModels(),
            max_repairs=max_repairs,
            locale="en" if locale == "en" else "es",
            dialect=self.profile,
        )


DEMO_NAME = "Retail demo (Ecuador)"


def builtin_spec(settings: Settings) -> ConnectionSpec:
    """The demo source configured from the environment (ADR-0006); not stored in the app DB."""
    agent, db = settings.agent, settings.demo_db
    return ConnectionSpec(
        key=agent.connection_key,
        name=DEMO_NAME,
        kind="postgresql",
        database=db.name,
        schema=agent.schema_name,
        host=db.host,
        port=db.port,
        username=db.user,
        password=db.password,
        as_of=agent.as_of,
        pii_columns=tuple(agent.pii_column_list),
        builtin=True,
    )


class ConnectionRegistry:
    def __init__(
        self,
        *,
        settings: Settings,
        sessions: async_sessionmaker[AsyncSession],
        store: PgDocumentStore,
        embedder: Embedder,
        builtin: ConnectionSpec,
        builtin_engine: AsyncEngine | None = None,
    ) -> None:
        self.settings = settings
        self._sessions = sessions
        self.store = store
        self._embedder = embedder
        self.builtin = builtin
        self._builtin_engine = builtin_engine
        keys = settings.connections.credentials_keys
        self.cipher = CredentialCipher(keys.get_secret_value()) if keys else None
        self._runtimes: dict[str, SourceRuntime] = {}
        self._locks: defaultdict[str, asyncio.Lock] = defaultdict(asyncio.Lock)

    # -- specs ---------------------------------------------------------------------------------

    def spec_from_row(self, row: DataConnection) -> ConnectionSpec:
        password = None
        if row.secret:
            if self.cipher is None:
                raise SourceError(
                    "NEXUS_CREDENTIALS_KEYS no está configurado: no se pueden leer credenciales."
                )
            password = SecretStr(self.cipher.decrypt(row.secret))
        return ConnectionSpec(
            key=row.key,
            name=row.name,
            kind=profile_for(row.kind).kind,
            database=row.database,
            schema=row.schema_name,
            host=row.host,
            port=row.port,
            username=row.username,
            password=password,
            as_of=row.as_of,
            pii_columns=tuple(c.strip() for c in row.pii_columns.split(",") if c.strip()),
        )

    async def spec(self, key: str) -> ConnectionSpec:
        if key == self.builtin.key:
            return self.builtin
        async with self._sessions() as session:
            row = await session.scalar(select(DataConnection).where(DataConnection.key == key))
        if row is None:
            raise UnknownSourceError(key)
        return self.spec_from_row(row)

    async def exists(self, key: str) -> bool:
        if key == self.builtin.key:
            return True
        async with self._sessions() as session:
            found = await session.scalar(select(DataConnection.id).where(DataConnection.key == key))
        return found is not None

    # -- runtimes ------------------------------------------------------------------------------

    async def get(self, key: str) -> SourceRuntime:
        runtime = self._runtimes.get(key)
        if runtime is not None:
            return runtime
        async with self._locks[key]:
            runtime = self._runtimes.get(key)
            if runtime is None:
                spec = await self.spec(key)
                try:
                    runtime = await self._build(spec)
                except SourceError:
                    raise
                except Exception as exc:
                    detail = str(getattr(exc, "orig", None) or exc).splitlines()[0][:200]
                    logger.warning("datasource.unavailable", key=key, error=detail)
                    raise SourceError(
                        f"No se pudo abrir la fuente de datos «{spec.name}»: {detail}"
                    ) from exc
                self._runtimes[key] = runtime
        return runtime

    def cached(self, key: str) -> SourceRuntime | None:
        return self._runtimes.get(key)

    async def _build(self, spec: ConnectionSpec) -> SourceRuntime:
        settings = self.settings
        agent = settings.agent
        profile = profile_for(spec.kind)
        await check_target(spec, settings)
        engine = (
            self._builtin_engine
            if spec.builtin and self._builtin_engine is not None
            else (
                create_engine(settings.demo_db, application_name="nexus-agent-reader")
                if spec.builtin
                else create_source_engine(spec, settings)
            )
        )
        try:
            catalog = await introspect_catalog(engine, spec.kind, spec.schema)
            samples = await collect_samples(engine, spec.kind, catalog, spec.pii_columns)
            rows = await row_estimates(engine, spec.kind, catalog)
            indexes = await existing_indexes(engine, spec.kind, catalog)
        except Exception:
            if not spec.builtin:
                await engine.dispose()
            raise
        glossary = (
            load_glossary(agent.glossary_path) if spec.builtin else Glossary.empty(profile.sqlglot)
        )
        tables = set(catalog.table_names)
        runtime = SourceRuntime(
            spec=spec,
            profile=profile,
            engine=engine,
            executor=ReadOnlyExecutor(
                engine,
                kind=spec.kind,
                statement_timeout_ms=agent.statement_timeout_ms,
                max_rows=agent.max_rows,
            ),
            catalog=catalog,
            policy=ValidationPolicy(
                allowed_tables=frozenset(tables | {t.lower() for t in tables}),
                allowed_schemas=frozenset({catalog.schema.lower()}),
                max_rows=agent.max_rows,
                dialect=profile.sqlglot,
                extra_allowed_functions=profile.extra_functions,
            ),
            glossary=glossary,
            masker=PiiMasker(spec.pii_columns, dialect=profile.sqlglot),
            retriever=HybridRetriever(
                store=self.store,
                embedder=self._embedder,
                catalog=catalog,
                glossary=glossary,
                connection_key=spec.key,
                samples=samples,
                load_examples=example_loader(self._sessions),
                max_tables=agent.retrieval_max_tables,
            ),
            samples=samples,
            as_of=spec.as_of or dt.datetime.now(dt.UTC).date(),
            rows=rows,
            indexes=indexes,
        )
        logger.info("datasource.ready", key=spec.key, kind=spec.kind, tables=len(catalog.tables))
        return runtime

    async def evict(self, key: str) -> None:
        runtime = self._runtimes.pop(key, None)
        if runtime is not None and not runtime.spec.builtin:
            await runtime.engine.dispose()

    async def close(self) -> None:
        for key in list(self._runtimes):
            await self.evict(key)

    # -- indexing ------------------------------------------------------------------------------

    async def index(self, key: str, *, force: bool = False) -> IndexReport:
        """Build (or confirm) the retrieval index; records the outcome on registered sources."""
        runtime = await self.get(key)
        try:
            report = await ensure_index(
                store=self.store,
                embedder=self._embedder,
                catalog=runtime.catalog,
                glossary=runtime.glossary,
                samples=runtime.samples,
                examples=await load_example_records(self._sessions, key),
                connection_key=key,
                force=force,
            )
        except Exception as exc:
            await self._record_index(key, "failed", str(exc)[:500])
            raise
        await self._record_index(key, "ready", None)
        return report

    async def _record_index(self, key: str, status: str, error: str | None) -> None:
        if key == self.builtin.key:
            return
        async with self._sessions() as session, session.begin():
            row = await session.scalar(select(DataConnection).where(DataConnection.key == key))
            if row is not None:
                row.index_status = status
                row.index_error = error
                if status == "ready":
                    row.indexed_at = dt.datetime.now(dt.UTC)
