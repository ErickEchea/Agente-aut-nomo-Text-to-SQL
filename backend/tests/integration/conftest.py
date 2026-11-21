"""Real PostgreSQL containers initialized with the *same* init scripts docker-compose uses."""

from __future__ import annotations

import time
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

import psycopg
import pytest
from pydantic import SecretStr
from testcontainers.core.container import DockerContainer
from testcontainers.core.image import DockerImage

from nexus.config import DatabaseSettings
from nexus.demo.generator import GeneratorConfig, generate
from nexus.demo.loader import LoadResult, load_dataset

REPO_ROOT = Path(__file__).resolve().parents[3]
SQL_DIR = REPO_ROOT / "data" / "retail"
OWNER_PASSWORD = "owner-test-password"
READER_PASSWORD = "reader-test-password"
APP_PASSWORD = "app-test-password"
SUPERUSER_PASSWORD = "superuser-test-password"
TEST_SCALE = 0.02


@dataclass(frozen=True)
class PgServer:
    host: str
    port: int

    def db(self, *, name: str, user: str, password: str) -> DatabaseSettings:
        return DatabaseSettings(
            host=self.host, port=self.port, name=name, user=user, password=SecretStr(password)
        )


def _wait_until_connectable(settings: DatabaseSettings, timeout_s: float = 90.0) -> None:
    """Init scripts run before the server accepts TCP; the target role only exists afterwards."""
    deadline = time.monotonic() + timeout_s
    while True:
        try:
            with psycopg.connect(settings.libpq_conninfo()):
                return
        except psycopg.OperationalError:
            if time.monotonic() > deadline:
                raise
            time.sleep(0.5)


def _start(image: str, init_dir: Path, env: dict[str, str]) -> DockerContainer:
    container = DockerContainer(image).with_exposed_ports(5432)
    container = container.with_env("POSTGRES_PASSWORD", SUPERUSER_PASSWORD)
    for key, value in env.items():
        container = container.with_env(key, value)
    return container.with_volume_mapping(str(init_dir), "/docker-entrypoint-initdb.d", "ro")


DEMO_IMAGE = "nexus-demo-db:test"


@pytest.fixture(scope="session")
def demo_image() -> Iterator[str]:
    """The compose demo-db image (PostgreSQL + HypoPG), built from the same Dockerfile."""
    with DockerImage(
        path=str(REPO_ROOT / "infra" / "postgres" / "demo-image"), tag=DEMO_IMAGE, clean_up=False
    ):
        yield DEMO_IMAGE


@pytest.fixture(scope="session")
def demo_server(demo_image: str) -> Iterator[PgServer]:
    container = _start(
        demo_image,
        REPO_ROOT / "infra" / "postgres" / "demo",
        {
            "NEXUS_DEMO_OWNER_PASSWORD": OWNER_PASSWORD,
            "NEXUS_DEMO_READER_PASSWORD": READER_PASSWORD,
        },
    )
    with container:
        server = PgServer(container.get_container_host_ip(), int(container.get_exposed_port(5432)))
        _wait_until_connectable(
            server.db(name="retail", user="nexus_reader", password=READER_PASSWORD)
        )
        yield server


@pytest.fixture(scope="session")
def owner_db(demo_server: PgServer) -> DatabaseSettings:
    return demo_server.db(name="retail", user="retail_owner", password=OWNER_PASSWORD)


@pytest.fixture(scope="session")
def reader_db(demo_server: PgServer) -> DatabaseSettings:
    return demo_server.db(name="retail", user="nexus_reader", password=READER_PASSWORD)


@pytest.fixture(scope="session")
def seeded(owner_db: DatabaseSettings) -> LoadResult:
    dataset = generate(GeneratorConfig(scale=TEST_SCALE, customers=2_000))
    return load_dataset(dataset, owner_db.libpq_conninfo(), SQL_DIR, force=True)


@pytest.fixture(scope="session")
def app_db() -> Iterator[DatabaseSettings]:
    container = _start(
        "pgvector/pgvector:0.8.7-pg18-trixie",
        REPO_ROOT / "infra" / "postgres" / "app",
        {"NEXUS_APP_DB_PASSWORD": APP_PASSWORD},
    )
    with container:
        server = PgServer(container.get_container_host_ip(), int(container.get_exposed_port(5432)))
        settings = server.db(name="nexus_app", user="nexus_app", password=APP_PASSWORD)
        _wait_until_connectable(settings)
        yield settings
