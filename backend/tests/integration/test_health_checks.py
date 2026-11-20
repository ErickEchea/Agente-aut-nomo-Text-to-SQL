from __future__ import annotations

import pytest

from nexus.config import DatabaseSettings
from nexus.db.engines import create_engine
from nexus.demo.loader import LoadResult
from nexus.health.checks import AppDatabaseCheck, DemoDatabaseCheck, run_check

pytestmark = pytest.mark.integration


async def test_app_database_check_sees_required_extensions(app_db: DatabaseSettings) -> None:
    engine = create_engine(app_db, application_name="test")
    try:
        result = await run_check(AppDatabaseCheck(engine), timeout_s=10)
    finally:
        await engine.dispose()
    assert result.ok, result.detail
    assert result.detail["extensions"] == ["pg_trgm", "unaccent", "vector"]


async def test_demo_check_passes_for_reader_role(
    seeded: LoadResult, reader_db: DatabaseSettings
) -> None:
    engine = create_engine(reader_db, application_name="test")
    try:
        result = await run_check(DemoDatabaseCheck(engine), timeout_s=10)
    finally:
        await engine.dispose()
    assert result.ok, result.detail
    assert result.detail == {"read_only": True, "retail_tables": 10}


async def test_demo_check_fails_for_a_role_that_is_not_read_only(
    seeded: LoadResult, owner_db: DatabaseSettings
) -> None:
    """Readiness must go red if the API is ever pointed at a writable role."""
    engine = create_engine(owner_db, application_name="test")
    try:
        result = await run_check(DemoDatabaseCheck(engine), timeout_s=10)
    finally:
        await engine.dispose()
    assert not result.ok
    assert result.detail["read_only"] is False
