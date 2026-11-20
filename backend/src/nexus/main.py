"""FastAPI application factory and service wiring."""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager
from datetime import UTC, datetime

import httpx
import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker

from nexus import __version__
from nexus.agent.catalog import SchemaCatalog, introspect
from nexus.agent.glossary import Glossary, load_glossary
from nexus.agent.graph import build_graph
from nexus.agent.state import AgentContext, AuditSink, EventSink, MemorySink
from nexus.api import audit, auth, health, memory, runs
from nexus.api.deps import AppServices
from nexus.config import Settings, get_settings
from nexus.db.engines import create_engine
from nexus.health.checks import AppDatabaseCheck, DemoDatabaseCheck, HealthCheck, OllamaCheck
from nexus.llm import LLMError, LLMProvider
from nexus.llm.ollama import OllamaProvider
from nexus.memory.store import ExampleIndexer
from nexus.observability.logging import configure_logging
from nexus.observability.middleware import REQUEST_ID_HEADER, RequestContextMiddleware
from nexus.rag.documents import collect_samples
from nexus.rag.embeddings import Embedder, profile_for
from nexus.rag.indexer import ensure_index, example_loader, load_example_records
from nexus.rag.retriever import HybridRetriever
from nexus.rag.store import PgDocumentStore
from nexus.runs.events import EventBroker
from nexus.runs.manager import RunManager
from nexus.security.accounts import ensure_bootstrap_admin
from nexus.security.pii import PiiMasker
from nexus.security.rate_limit import TokenBucketLimiter
from nexus.security.tokens import TokenService
from nexus.sql.executor import ReadOnlyExecutor
from nexus.sql.validator import ValidationPolicy

logger = structlog.get_logger("nexus.app")


async def _build_retriever(
    settings: Settings,
    *,
    sessions: async_sessionmaker[AsyncSession],
    demo_engine: AsyncEngine,
    store: PgDocumentStore,
    embedder: Embedder,
    catalog: SchemaCatalog,
    glossary: Glossary,
) -> HybridRetriever:
    """Schema RAG (ADR-0007): sample values + index (rebuilt only when its fingerprint changes)."""
    agent_cfg = settings.agent
    samples = await collect_samples(demo_engine, catalog, agent_cfg.pii_column_list)
    try:
        report = await ensure_index(
            store=store,
            embedder=embedder,
            catalog=catalog,
            glossary=glossary,
            samples=samples,
            examples=await load_example_records(sessions, agent_cfg.connection_key),
            connection_key=agent_cfg.connection_key,
        )
        logger.info("rag.index_ready", rebuilt=report.rebuilt, documents=report.documents)
    except LLMError as exc:  # Ollama not ready: serve with lexical retrieval / full schema
        logger.warning("rag.index_unavailable", error=str(exc))
    return HybridRetriever(
        store=store,
        embedder=embedder,
        catalog=catalog,
        glossary=glossary,
        connection_key=agent_cfg.connection_key,
        samples=samples,
        load_examples=example_loader(sessions),
        max_tables=agent_cfg.retrieval_max_tables,
    )


def create_app(
    settings: Settings | None = None,
    *,
    health_checks: Sequence[HealthCheck] | None = None,
    llm: LLMProvider | None = None,
) -> FastAPI:
    """Build the app.

    ``health_checks`` runs a dependency-free app (health endpoints only) for unit tests.
    ``llm`` replaces the Ollama provider (integration tests use a scripted model).
    """
    settings = settings or get_settings()
    configure_logging(settings.log_level, json=settings.log_json)

    @asynccontextmanager
    async def lifespan(app: FastAPI) -> AsyncIterator[None]:
        if health_checks is not None:
            app.state.health_checks = list(health_checks)
            yield
            return

        app_engine = create_engine(settings.app_db, application_name="nexus-api")
        demo_engine = create_engine(settings.demo_db, application_name="nexus-agent-reader")
        ollama_client = httpx.AsyncClient(
            base_url=str(settings.ollama.base_url), timeout=settings.ollama.request_timeout_s
        )
        sessions = async_sessionmaker(app_engine, expire_on_commit=False)
        app.state.health_checks = [
            AppDatabaseCheck(app_engine),
            DemoDatabaseCheck(demo_engine),
            OllamaCheck(ollama_client, settings.ollama.required_models),
        ]

        agent_cfg = settings.agent
        catalog = await introspect(demo_engine, agent_cfg.schema_name)
        glossary = load_glossary(agent_cfg.glossary_path)
        provider = llm or OllamaProvider(
            str(settings.ollama.base_url),
            settings.ollama.llm_model,
            settings.ollama.embedding_model,
            timeout_s=agent_cfg.llm_timeout_s,
        )
        executor = ReadOnlyExecutor(
            demo_engine,
            statement_timeout_ms=agent_cfg.statement_timeout_ms,
            max_rows=agent_cfg.max_rows,
        )
        policy = ValidationPolicy(
            allowed_tables=catalog.table_names,
            allowed_schemas=frozenset({agent_cfg.schema_name}),
            max_rows=agent_cfg.max_rows,
        )
        masker = PiiMasker(agent_cfg.pii_column_list)
        as_of = agent_cfg.as_of or datetime.now(UTC).date()

        store = PgDocumentStore(sessions)
        embedder = Embedder(provider, profile_for(settings.ollama.embedding_model))
        retriever = await _build_retriever(
            settings,
            sessions=sessions,
            demo_engine=demo_engine,
            store=store,
            embedder=embedder,
            catalog=catalog,
            glossary=glossary,
        )

        def context_factory(
            events: EventSink, audit_sink: AuditSink, memory_sink: MemorySink, locale: str
        ) -> AgentContext:
            return AgentContext(
                llm=provider,
                catalog=catalog,
                glossary=glossary,
                policy=policy,
                executor=executor,
                as_of=as_of,
                events=events,
                audit=audit_sink,
                masker=masker,
                retriever=retriever,
                memory=memory_sink,
                max_repairs=agent_cfg.max_repairs,
                locale="en" if locale == "en" else "es",
            )

        manager = RunManager(sessions, build_graph(), context_factory, EventBroker())
        app.state.services = AppServices(
            settings=settings,
            sessions=sessions,
            tokens=TokenService(
                settings.security.jwt_secret.get_secret_value(),
                settings.security.access_token_ttl_s,
            ),
            limiter=TokenBucketLimiter(),
            runs=manager,
            examples=ExampleIndexer(store, embedder, agent_cfg.connection_key),
        )

        security = settings.security
        if security.bootstrap_admin_email and security.bootstrap_admin_password:
            async with sessions() as session, session.begin():
                await ensure_bootstrap_admin(
                    session,
                    security.bootstrap_admin_email,
                    security.bootstrap_admin_password.get_secret_value(),
                )

        logger.info(
            "app.startup",
            version=__version__,
            env=settings.env,
            tables=len(catalog.tables),
            model=provider.default_model,
            as_of=as_of.isoformat(),
        )
        try:
            yield
        finally:
            await manager.shutdown()
            await ollama_client.aclose()
            await demo_engine.dispose()
            await app_engine.dispose()
            logger.info("app.shutdown")

    app = FastAPI(
        title="NEXUS AI",
        version=__version__,
        lifespan=lifespan,
        docs_url="/api/docs" if settings.env != "production" else None,
        redoc_url=None,
        openapi_url="/api/openapi.json",
    )
    app.state.health_timeout_s = settings.ollama.request_timeout_s

    # Order matters: the request-context middleware is outermost, so every log line
    # (including CORS rejections) carries request_id.
    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_origins,
        allow_credentials=True,
        allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
        allow_headers=["Authorization", "Content-Type", "Last-Event-ID", REQUEST_ID_HEADER],
        expose_headers=[REQUEST_ID_HEADER, "Retry-After"],
    )
    app.add_middleware(RequestContextMiddleware)

    for router in (health.router, auth.router, runs.router, memory.router, audit.router):
        app.include_router(router)
    return app
