"""Async SQLAlchemy engine factory.

The app DB and every queried data source get **separate** engines and pools (ADR-0005, ADR-0006).
"""

from __future__ import annotations

from sqlalchemy.ext.asyncio import AsyncEngine, create_async_engine

from nexus.config import DatabaseSettings


def create_engine(settings: DatabaseSettings, *, application_name: str) -> AsyncEngine:
    return create_async_engine(
        settings.sqlalchemy_url(),
        pool_size=settings.pool_size,
        max_overflow=0,
        pool_pre_ping=True,
        pool_recycle=1800,
        connect_args={
            "timeout": settings.connect_timeout_s,
            "server_settings": {"application_name": application_name},
        },
    )
