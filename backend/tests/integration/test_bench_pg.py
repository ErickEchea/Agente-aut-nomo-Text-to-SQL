"""Benchmark plumbing against real PostgreSQL: migration, gold SQL, persistence and the API."""

from __future__ import annotations

import asyncio
import uuid
from collections.abc import Iterator

import pytest
from alembic.autogenerate import compare_metadata
from alembic.migration import MigrationContext
from fastapi.testclient import TestClient
from sqlalchemy.engine import Connection
from sqlalchemy.ext.asyncio import async_sessionmaker

from nexus.agent.catalog import introspect
from nexus.bench.golden import GoldenSet
from nexus.bench.metrics import summarize
from nexus.bench.runner import BenchConfig, ItemOutcome
from nexus.bench.store import fail_run, finish_run, start_run
from nexus.config import DatabaseSettings, Settings
from nexus.db.engines import create_engine
from nexus.db.migrate import upgrade
from nexus.db.models import Base
from nexus.demo.loader import LoadResult
from nexus.main import create_app
from nexus.sql.executor import ReadOnlyExecutor
from nexus.sql.validator import ValidationPolicy, validate_sql
from tests.integration.conftest import REPO_ROOT
from tests.integration.test_api import ADMIN, login, scripted

pytestmark = pytest.mark.integration
BENCH_TABLES = {"benchmark_runs", "benchmark_results"}


@pytest.fixture(scope="module")
def migrated_app_db(app_db: DatabaseSettings) -> DatabaseSettings:
    """The session's app DB, migrated (idempotent; no extra users: the bootstrap admin suffices)."""
    upgrade(app_db.sqlalchemy_url().render_as_string(hide_password=False))
    return app_db


@pytest.fixture(scope="module")
def client(
    migrated_app_db: DatabaseSettings, reader_db: DatabaseSettings, seeded: LoadResult
) -> Iterator[TestClient]:
    settings = Settings(
        env="test",
        app_db=migrated_app_db,
        demo_db=reader_db,
        security={
            "jwt_secret": "integration-secret-" + "x" * 32,
            "bootstrap_admin_email": ADMIN[0],
            "bootstrap_admin_password": ADMIN[1],
        },
        agent={"as_of": "2026-11-01", "glossary_path": REPO_ROOT / "data" / "glossary.yaml"},
        rate_limit={"login_per_minute": 60},
    )  # type: ignore[arg-type]
    with TestClient(create_app(settings, llm=scripted())) as test_client:
        yield test_client


def _diff(connection: Connection) -> list[object]:
    context = MigrationContext.configure(connection, opts={"compare_type": True})
    return compare_metadata(context, Base.metadata)


def test_benchmark_migration_matches_the_models(
    migrated_app_db: DatabaseSettings,
) -> None:
    async def check() -> list[object]:
        engine = create_engine(migrated_app_db, application_name="test-drift")
        async with engine.connect() as connection:
            diff = await connection.run_sync(_diff)
        await engine.dispose()
        return diff

    def touches_benchmark(entry: object) -> bool:
        return any(name in repr(entry) for name in BENCH_TABLES)

    assert [d for d in asyncio.run(check()) if touches_benchmark(d)] == []


async def test_every_gold_query_runs_read_only_on_the_demo_schema(
    reader_db: DatabaseSettings, seeded: LoadResult
) -> None:
    golden = GoldenSet.load(REPO_ROOT / "bench" / "golden")
    engine = create_engine(reader_db, application_name="test-gold")
    try:
        catalog = await introspect(engine, "retail")
        policy = ValidationPolicy(allowed_tables=frozenset(catalog.table_names), max_rows=1000)
        executor = ReadOnlyExecutor(engine, statement_timeout_ms=60_000, max_rows=1000)
        ran = 0
        for item in golden.items:
            for sql in item.gold_sql:
                result = await executor.execute(validate_sql(sql, policy))
                assert result.columns, item.id
                ran += 1
        assert ran >= 110
    finally:
        await engine.dispose()


def _outcome(item: str, difficulty: str, correct: bool, ms: float) -> ItemOutcome:
    return ItemOutcome(
        item_id=item,
        difficulty=difficulty,
        question=f"¿{item}?",
        status="answered",
        correct=correct,
        reason="ok" if correct else "row_values",
        latency_ms=ms,
        sql_attempts=1,
        repairs=0 if correct else 2,
        sql=["SELECT 1"],
    )


@pytest.fixture(scope="module")
def stored_runs(
    migrated_app_db: DatabaseSettings,
) -> dict[str, uuid.UUID]:
    async def store() -> dict[str, uuid.UUID]:
        engine = create_engine(migrated_app_db, application_name="test-bench-store")
        sessions = async_sessionmaker(engine, expire_on_commit=False)
        ids = {}
        for name, outcomes in {
            "accurate-slow": [
                _outcome("e001", "easy", True, 9000),
                _outcome("m001", "medium", True, 9000),
                _outcome("h001", "hard", True, 9000),
                _outcome("h031", "hard", True, 9000),
            ],
            "fast-wrong": [
                _outcome("e001", "easy", True, 1000),
                _outcome("m001", "medium", False, 1000),
            ],
        }.items():
            config = BenchConfig(name=name, model=f"{name}:1b")
            run_id = await start_run(
                sessions, config, subset="full", dataset_version="1.0.0", git_sha="abc"
            )
            await finish_run(sessions, run_id, outcomes, summarize(outcomes))
            ids[name] = run_id
        broken = await start_run(
            sessions,
            BenchConfig(name="broken", model="x:1b"),
            subset="full",
            dataset_version="1.0.0",
            git_sha=None,
        )
        await fail_run(sessions, broken, "RuntimeError: boom")
        ids["broken"] = broken
        await engine.dispose()
        return ids

    return asyncio.run(store())


def test_benchmark_overview_and_detail(
    client: TestClient,
    stored_runs: dict[str, uuid.UUID],
) -> None:
    assert client.get("/api/benchmark").status_code == 401
    viewer = login(client, ADMIN)  # any authenticated role may read the benchmark
    overview = client.get("/api/benchmark", headers=viewer)
    assert overview.status_code == 200, overview.text
    body = overview.json()
    names = [run["config"]["name"] for run in body["runs"]]
    assert names == [
        "accurate-slow",
        "fast-wrong",
    ]  # failed runs are not shown; best accuracy first
    assert body["selected"] == "accurate-slow"
    assert body["reference_items"] == ["h001", "h031"]
    assert [run["eligible"] for run in body["runs"]] == [True, False]
    assert body["selection_margin"] == 0.02
    assert body["serving"]["model"]
    first = body["runs"][0]
    assert (
        first["summary"]["accuracy"] == 1.0
        and first["summary"]["by_difficulty"]["easy"]["items"] == 1
    )

    detail = client.get(f"/api/benchmark/runs/{stored_runs['fast-wrong']}", headers=viewer).json()
    assert [r["item_id"] for r in detail["results"]] == ["e001", "m001"]
    wrong = detail["results"][1]
    assert wrong["correct"] is False and wrong["reason"] == "row_values" and wrong["repairs"] == 2
    assert wrong["sql"] == ["SELECT 1"]

    admin = viewer
    assert (
        client.get(f"/api/benchmark/runs/{stored_runs['broken']}", headers=admin).status_code == 404
    )
    assert client.get(f"/api/benchmark/runs/{uuid.uuid4()}", headers=admin).status_code == 404
