"""FastAPI application factory."""

from __future__ import annotations

from collections.abc import AsyncIterator, Sequence
from contextlib import asynccontextmanager

import httpx
import structlog
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from nexus import __version__
from nexus.api import health
from nexus.config import Settings, get_settings
from nexus.db.engines import create_engine
from nexus.health.checks import AppDatabaseCheck, DemoDatabaseCheck, HealthCheck, OllamaCheck
from nexus.observability.logging import configure_logging
from nexus.observability.middleware import REQUEST_ID_HEADER, RequestContextMiddleware

logger = structlog.get_logger("nexus.app")


def create_app(
    settings: Settings | None = None,
    *,
    health_checks: Sequence[HealthCheck] | None = None,
) -> FastAPI:
    """Build the app. ``health_checks`` lets tests inject checks instead of real dependencies."""
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
            base_url=str(settings.ollama.base_url),
            timeout=settings.ollama.request_timeout_s,
        )
        app.state.app_engine = app_engine
        app.state.demo_engine = demo_engine
        app.state.ollama_client = ollama_client
        app.state.health_checks = [
            AppDatabaseCheck(app_engine),
            DemoDatabaseCheck(demo_engine),
            OllamaCheck(ollama_client, settings.ollama.required_models),
        ]
        logger.info("app.startup", version=__version__, env=settings.env)
        try:
            yield
        finally:
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
        allow_headers=["Authorization", "Content-Type", REQUEST_ID_HEADER],
        expose_headers=[REQUEST_ID_HEADER],
    )
    app.add_middleware(RequestContextMiddleware)

    app.include_router(health.router)
    return app
