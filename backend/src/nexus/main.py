"""FastAPI application factory and service wiring."""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager

import httpx
import structlog
from fastapi import APIRouter, FastAPI
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy.ext.asyncio import async_sessionmaker

from nexus import __version__
from nexus.agent.graph import build_graph
from nexus.agent.state import AgentContext, AuditSink, EventSink, MemorySink, NodeModels
from nexus.api import (
    audit,
    auth,
    benchmark,
    connections,
    dashboards,
    health,
    insights,
    memory,
    runs,
)
from nexus.api.deps import AppServices
from nexus.config import Settings, get_settings
from nexus.datasources.registry import ConnectionRegistry, builtin_spec
from nexus.db.engines import create_engine
from nexus.health.checks import AppDatabaseCheck, DemoDatabaseCheck, HealthCheck, OllamaCheck
from nexus.llm import LLMError, LLMProvider
from nexus.llm.ollama import OllamaProvider
from nexus.memory.store import ExampleIndexer
from nexus.observability.logging import configure_logging
from nexus.observability.middleware import REQUEST_ID_HEADER, RequestContextMiddleware
from nexus.rag.embeddings import Embedder, profile_for
from nexus.rag.store import PgDocumentStore
from nexus.runs.events import EventBroker
from nexus.runs.manager import RunManager
from nexus.security.accounts import ensure_bootstrap_admin
from nexus.security.rate_limit import TokenBucketLimiter
from nexus.security.tokens import TokenService

logger = structlog.get_logger("nexus.app")
ROUTERS: tuple[APIRouter, ...] = (
    health.router,
    auth.router,
    runs.router,
    insights.router,
    memory.router,
    dashboards.router,
    connections.router,
    benchmark.router,
    audit.router,
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
        provider = llm or OllamaProvider(
            str(settings.ollama.base_url),
            settings.ollama.llm_model,
            settings.ollama.embedding_model,
            timeout_s=agent_cfg.llm_timeout_s,
            think=settings.ollama.think,
        )
        store = PgDocumentStore(sessions)
        embedder = Embedder(provider, profile_for(settings.ollama.embedding_model))
        registry = ConnectionRegistry(
            settings=settings,
            sessions=sessions,
            store=store,
            embedder=embedder,
            builtin=builtin_spec(settings),
            builtin_engine=demo_engine,
        )
        demo = await registry.get(agent_cfg.connection_key)
        try:  # schema RAG index (rebuilt only when its fingerprint changes)
            report = await registry.index(agent_cfg.connection_key)
            logger.info("rag.index_ready", rebuilt=report.rebuilt, documents=report.documents)
        except LLMError as exc:  # Ollama not ready: serve with lexical retrieval / full schema
            logger.warning("rag.index_unavailable", error=str(exc))

        async def context_factory(
            connection_key: str,
            events: EventSink,
            audit_sink: AuditSink,
            memory_sink: MemorySink,
            locale: str,
        ) -> AgentContext:
            source = await registry.get(connection_key)
            return source.agent_context(
                llm=provider,
                events=events,
                audit=audit_sink,
                memory=memory_sink,
                locale=locale,
                max_repairs=agent_cfg.max_repairs,
                models=NodeModels(**agent_cfg.models.routing()),
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
            examples=ExampleIndexer(store, embedder),
            registry=registry,
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
            tables=len(demo.catalog.tables),
            model=provider.default_model,
            as_of=demo.as_of.isoformat(),
            connections_enabled=registry.cipher is not None,
        )
        try:
            yield
        finally:
            await manager.shutdown()
            await registry.close()
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

    for router in ROUTERS:
        app.include_router(router)
    return app
