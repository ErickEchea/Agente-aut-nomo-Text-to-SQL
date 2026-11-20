from __future__ import annotations

import psycopg
import pytest

from nexus.config import DatabaseSettings
from nexus.demo.generator import GeneratorConfig, generate
from nexus.demo.loader import LoadResult, load_dataset
from tests.integration.conftest import SQL_DIR, TEST_SCALE

pytestmark = pytest.mark.integration


def _scalar(settings: DatabaseSettings, query: str) -> object:
    with psycopg.connect(settings.libpq_conninfo()) as conn:
        row = conn.execute(query).fetchone()
    assert row is not None
    return row[0]


def test_loaded_row_counts_match_generator(seeded: LoadResult, owner_db: DatabaseSettings) -> None:
    assert seeded.loaded
    for table, expected in seeded.row_counts.items():
        assert _scalar(owner_db, f"SELECT count(*) FROM retail.{table}") == expected, table


def test_reload_is_idempotent_unless_forced(seeded: LoadResult, owner_db: DatabaseSettings) -> None:
    dataset = generate(GeneratorConfig(scale=TEST_SCALE, customers=2_000))
    again = load_dataset(dataset, owner_db.libpq_conninfo(), SQL_DIR)
    assert again.loaded is False
    assert again.checksum == seeded.checksum
    forced = load_dataset(dataset, owner_db.libpq_conninfo(), SQL_DIR, force=True)
    assert forced.loaded is True
    assert _scalar(owner_db, "SELECT checksum FROM retail_meta.dataset") == seeded.checksum


def test_every_table_and_column_has_a_comment(
    seeded: LoadResult, owner_db: DatabaseSettings
) -> None:
    missing_tables = _scalar(
        owner_db,
        """
        SELECT coalesce(string_agg(c.relname, ', '), '')
        FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = 'retail' AND c.relkind = 'r'
          AND obj_description(c.oid, 'pg_class') IS NULL
        """,
    )
    missing_columns = _scalar(
        owner_db,
        """
        SELECT coalesce(string_agg(c.relname || '.' || a.attname, ', '), '')
        FROM pg_attribute a
        JOIN pg_class c ON c.oid = a.attrelid
        JOIN pg_namespace n ON n.oid = c.relnamespace
        WHERE n.nspname = 'retail' AND c.relkind = 'r' AND a.attnum > 0 AND NOT a.attisdropped
          AND col_description(c.oid, a.attnum) IS NULL
        """,
    )
    assert missing_tables == ""
    assert missing_columns == ""
    assert (
        _scalar(
            owner_db,
            "SELECT count(*) FROM pg_class c JOIN pg_namespace n ON n.oid = c.relnamespace "
            "WHERE n.nspname = 'retail' AND c.relkind = 'r'",
        )
        == 10
    )


def test_foreign_keys_exist(seeded: LoadResult, owner_db: DatabaseSettings) -> None:
    fks = _scalar(
        owner_db,
        "SELECT string_agg(c.conname, ',' ORDER BY c.conname) FROM pg_constraint c "
        "JOIN pg_namespace n ON n.oid = c.connamespace "
        "WHERE n.nspname = 'retail' AND c.contype = 'f'",
    )
    assert str(fks).split(",") == [
        "detalle_producto_fk",
        "detalle_venta_fk",
        "devoluciones_detalle_fk",
        "devoluciones_venta_fk",
        "empleados_sucursal_fk",
        "empleados_supervisor_fk",
        "inventario_producto_fk",
        "inventario_sucursal_fk",
        "productos_categoria_fk",
        "sucursales_region_fk",
        "ventas_cliente_fk",
        "ventas_empleado_fk",
        "ventas_sucursal_fk",
    ]


def test_planted_missing_index_on_detalle_producto(
    seeded: LoadResult, owner_db: DatabaseSettings
) -> None:
    """ADR-0017 anomaly #7: the optimizer demo relies on this index NOT existing."""
    leading_columns = _scalar(
        owner_db,
        """
        SELECT coalesce(string_agg(a.attname, ','), '')
        FROM pg_index i
        JOIN pg_class t ON t.oid = i.indrelid
        JOIN pg_attribute a ON a.attrelid = t.oid AND a.attnum = i.indkey[0]
        WHERE t.relname = 'detalle_ventas'
        """,
    )
    assert "producto_id" not in str(leading_columns).split(",")
    assert "venta_id" in str(leading_columns).split(",")
