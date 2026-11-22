"""Data-source targets: NEXUS's own services and forbidden ranges are refused (ADR-0023)."""

from __future__ import annotations

import ipaddress
import socket

import pytest
from pydantic import SecretStr

from nexus.config import Settings
from nexus.datasources.registry import ConnectionSpec, SourceError, check_target, probe
from nexus.datasources.targets import IpAddress, internal_services, resolve, target_problem

DNS = {
    "app-db": {"172.18.0.2"},
    "ollama": {"172.18.0.3"},
    "warehouse.internal": {"10.20.0.5"},
    "metadata.cloud": {"169.254.169.254"},
    "mapped.example": {"::ffff:169.254.169.254"},
    "anything.example": {"0.0.0.0"},  # noqa: S104 — the address under test, not a bind
    "multicast.example": {"224.0.0.1"},
    "alias-of-app-db": {"172.18.0.2"},
    "localhost": {"127.0.0.1", "::1"},
}


async def fake_resolver(host: str, port: int) -> frozenset[IpAddress]:
    if host not in DNS:
        raise socket.gaierror(socket.EAI_NONAME, "Name or service not known")
    return frozenset(ipaddress.ip_address(a) for a in DNS[host])


def _settings(app_host: str = "app-db", app_port: int = 5432) -> Settings:
    db = {"host": app_host, "port": app_port, "name": "n", "user": "u", "password": "p"}
    return Settings(
        app_db=db,
        demo_db={**db, "host": "demo-db"},
        security={"jwt_secret": "k" * 32},
        ollama={"base_url": "http://ollama:11434"},
    )  # type: ignore[arg-type]


async def _problem(host: str, port: int, settings: Settings | None = None) -> str | None:
    return await target_problem(host, port, settings or _settings(), resolver=fake_resolver)


def test_internal_services_come_from_settings() -> None:
    assert internal_services(_settings()) == (
        ("base de datos de la aplicación", "app-db", 5432),
        ("Ollama", "ollama", 11434),
    )


async def test_an_ordinary_database_host_is_allowed() -> None:
    assert await _problem("warehouse.internal", 5432) is None


@pytest.mark.parametrize(
    "host", ["metadata.cloud", "mapped.example", "anything.example", "multicast.example"]
)
async def test_link_local_multicast_and_unspecified_addresses_are_refused(host: str) -> None:
    problem = await _problem(host, 5432)
    assert problem is not None and "no permitida" in problem


@pytest.mark.parametrize(("host", "port"), [("app-db", 5432), ("alias-of-app-db", 5432)])
async def test_the_application_database_is_refused_by_address(host: str, port: int) -> None:
    problem = await _problem(host, port)
    assert problem is not None and "base de datos de la aplicación" in problem


async def test_ollama_is_refused() -> None:
    problem = await _problem("ollama", 11434)
    assert problem is not None and "Ollama" in problem


async def test_another_port_on_the_same_address_is_a_different_service() -> None:
    # Testcontainers publish every database on localhost: only the app DB's own port is refused.
    settings = _settings(app_host="localhost", app_port=55432)
    assert await _problem("localhost", 3306, settings) is None
    assert await _problem("localhost", 55432, settings) is not None


async def test_unresolvable_hosts_are_reported() -> None:
    assert (
        await _problem("nowhere.invalid", 5432) == "No se pudo resolver el host «nowhere.invalid»."
    )


async def test_the_real_resolver_handles_literal_addresses() -> None:
    assert await resolve("127.0.0.1", 5432) == frozenset({ipaddress.ip_address("127.0.0.1")})
    assert await resolve("::ffff:169.254.169.254", 80) == frozenset(
        {ipaddress.ip_address("169.254.169.254")}
    )


def _spec(kind: str, host: str | None, port: int | None = None) -> ConnectionSpec:
    return ConnectionSpec(
        key="k",
        name="K",
        kind=kind,  # type: ignore[arg-type]
        database="db.sqlite" if kind == "sqlite" else "db",
        schema="main" if kind == "sqlite" else "public",
        host=host,
        port=port,
        username="u",
        password=SecretStr("p"),
    )


async def test_check_target_uses_the_engine_default_port_and_skips_sqlite() -> None:
    settings = _settings(app_host="169.254.10.10")
    with pytest.raises(SourceError, match="no permitida"):
        await check_target(_spec("postgresql", "169.254.10.10"), settings)
    await check_target(_spec("sqlite", None), settings)


async def test_probe_refuses_before_any_driver_connects() -> None:
    result = await probe(_spec("mysql", "169.254.169.254", 3306), _settings())
    assert not result.ok
    assert result.error is not None and "no permitida" in result.error
