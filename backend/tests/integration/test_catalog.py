"""Schema introspection against the real demo database (as the agent's read-only role)."""

from __future__ import annotations

import pytest

from nexus.agent.catalog import ForeignKey, introspect
from nexus.config import DatabaseSettings
from nexus.db.engines import create_engine
from nexus.demo.loader import LoadResult

pytestmark = pytest.mark.integration


async def test_introspection_reads_tables_comments_keys(
    seeded: LoadResult, reader_db: DatabaseSettings
) -> None:
    engine = create_engine(reader_db, application_name="test-catalog")
    try:
        catalog = await introspect(engine)
    finally:
        await engine.dispose()

    assert catalog.table_names == {
        "regiones", "sucursales", "categorias", "productos", "clientes",
        "empleados", "ventas", "detalle_ventas", "inventario", "devoluciones",
    }  # fmt: skip
    ventas = catalog.tables["ventas"]
    assert ventas.primary_key == ("venta_id",)
    assert ForeignKey("sucursal_id", "sucursales", "sucursal_id") in ventas.foreign_keys
    assert all(fk.ref_table is not None for t in catalog.tables.values() for fk in t.foreign_keys)
    assert catalog.tables["inventario"].primary_key == ("sucursal_id", "producto_id", "fecha_corte")
    assert ventas.comment.startswith("Cabecera de cada venta")
    rendered = catalog.render(["ventas"])
    assert "venta_id integer [PK]" in rendered
    assert "sucursal_id integer [FK→sucursales.sucursal_id, NOT NULL]" in rendered
    assert "None" not in catalog.render()
