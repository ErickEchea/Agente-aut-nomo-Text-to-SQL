"""ADR-0005 layer B: the agent's database role must be unable to change anything, on its own.

These tests deliberately bypass the (future) SQL validator and talk to PostgreSQL directly.
"""

from __future__ import annotations

import psycopg
import pytest
from psycopg import errors

from nexus.config import DatabaseSettings
from nexus.demo.loader import LoadResult

pytestmark = pytest.mark.integration

WRITES = [
    "INSERT INTO regiones (region_id, nombre, descripcion) VALUES (99, 'x', 'x')",
    "UPDATE productos SET precio_lista = 0.01",
    "DELETE FROM ventas",
    "TRUNCATE detalle_ventas",
    "CREATE TABLE retail.pwned (id int)",
    "CREATE TABLE public.pwned (id int)",
    "DROP TABLE clientes",
    "ALTER TABLE clientes ADD COLUMN x int",
    "CREATE INDEX pwned_idx ON ventas (total)",
    "COPY clientes TO PROGRAM 'id'",
    "CREATE FUNCTION pwn() RETURNS int LANGUAGE sql AS 'SELECT 1'",
]

FORBIDDEN_FUNCTIONS = [
    "SELECT pg_sleep(0.01)",
    "SELECT pg_sleep_for('10 milliseconds')",
    "SELECT set_config('statement_timeout', '0', false)",
    "SELECT pg_terminate_backend(pg_backend_pid())",
    "SELECT pg_read_file('/etc/passwd')",
    "SELECT pg_ls_dir('.')",
    "SELECT lo_import('/etc/passwd')",
]


def _connect(settings: DatabaseSettings) -> psycopg.Connection:
    return psycopg.connect(settings.libpq_conninfo(), autocommit=True)


def _counts(settings: DatabaseSettings) -> dict[str, int]:
    with _connect(settings) as conn:
        tables = [
            "regiones", "sucursales", "categorias", "productos", "clientes",
            "empleados", "ventas", "detalle_ventas", "inventario", "devoluciones",
        ]  # fmt: skip
        return {t: int(conn.execute(f"SELECT count(*) FROM {t}").fetchone()[0]) for t in tables}  # type: ignore[index]


def test_reader_can_query_the_retail_schema(
    seeded: LoadResult, reader_db: DatabaseSettings
) -> None:
    counts = _counts(reader_db)
    assert counts == {k: v for k, v in seeded.row_counts.items() if k in counts}
    assert counts["detalle_ventas"] > 5_000


def test_reader_session_defaults(seeded: LoadResult, reader_db: DatabaseSettings) -> None:
    with _connect(reader_db) as conn:
        settings = {
            name: conn.execute(f"SHOW {name}").fetchone()[0]  # type: ignore[index]
            for name in (
                "default_transaction_read_only",
                "statement_timeout",
                "lock_timeout",
                "idle_in_transaction_session_timeout",
                "search_path",
            )
        }
    assert settings == {
        "default_transaction_read_only": "on",
        "statement_timeout": "15s",
        "lock_timeout": "2s",
        "idle_in_transaction_session_timeout": "30s",
        "search_path": "retail",
    }


@pytest.mark.parametrize("statement", WRITES)
def test_writes_fail_in_default_read_only_transactions(
    seeded: LoadResult, reader_db: DatabaseSettings, statement: str
) -> None:
    with _connect(reader_db) as conn, pytest.raises(psycopg.Error) as exc_info:
        conn.execute(statement)
    assert exc_info.value.sqlstate in {"25006", "42501"}  # read-only transaction / no privilege


@pytest.mark.parametrize("statement", WRITES)
def test_writes_fail_even_after_disabling_read_only(
    seeded: LoadResult, reader_db: DatabaseSettings, statement: str
) -> None:
    """Privileges alone block writes: flipping the session read-only flag gains nothing."""
    with _connect(reader_db) as conn:
        conn.execute("SET default_transaction_read_only = off")
        with pytest.raises(psycopg.Error) as exc_info:
            conn.execute(statement)
    assert exc_info.value.sqlstate in {"42501", "42883"}  # insufficient privilege / not permitted


@pytest.mark.parametrize("statement", FORBIDDEN_FUNCTIONS)
def test_dangerous_functions_are_not_executable(
    seeded: LoadResult, reader_db: DatabaseSettings, statement: str
) -> None:
    with _connect(reader_db) as conn, pytest.raises(errors.InsufficientPrivilege):
        conn.execute(statement)


def test_grant_by_reader_has_no_effect(seeded: LoadResult, reader_db: DatabaseSettings) -> None:
    """A GRANT without grant option only raises a WARNING in PostgreSQL, so check its effect."""
    with _connect(reader_db) as conn:
        conn.execute("SET default_transaction_read_only = off")
        conn.execute("GRANT SELECT ON clientes TO PUBLIC")
        grants = conn.execute(
            "SELECT count(*) FROM information_schema.role_table_grants "
            "WHERE table_schema = 'retail' AND table_name = 'clientes' AND grantee = 'PUBLIC'"
        ).fetchone()
    assert grants == (0,)


def test_reader_cannot_read_dataset_metadata(
    seeded: LoadResult, reader_db: DatabaseSettings
) -> None:
    with _connect(reader_db) as conn, pytest.raises(errors.InsufficientPrivilege):
        conn.execute("SELECT * FROM retail_meta.dataset")


def test_reader_cannot_connect_to_other_databases(
    demo_server_db_postgres: DatabaseSettings,
) -> None:
    with pytest.raises(psycopg.OperationalError, match="permission denied for database"):
        psycopg.connect(demo_server_db_postgres.libpq_conninfo())


def test_data_unchanged_after_attacks(seeded: LoadResult, reader_db: DatabaseSettings) -> None:
    counts = _counts(reader_db)
    assert counts == {k: v for k, v in seeded.row_counts.items() if k in counts}


@pytest.fixture
def demo_server_db_postgres(reader_db: DatabaseSettings) -> DatabaseSettings:
    return reader_db.model_copy(update={"name": "postgres"})
