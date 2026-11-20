"""Properties of the full-scale generated dataset (ADR-0017)."""

from datetime import date

import numpy as np
import pytest
from numpy.typing import NDArray

from nexus.demo import catalog as cat
from nexus.demo.generator import Dataset, GeneratorConfig, generate, is_valid_cedula
from nexus.demo.tables import NULL_INT


@pytest.fixture(scope="module")
def ds() -> Dataset:
    return generate()


def col(ds: Dataset, table: str, column: str) -> NDArray[np.generic]:
    return ds.table(table).data[column]


def line_days(ds: Dataset) -> NDArray[np.datetime64]:
    sale_day = col(ds, "ventas", "fecha_venta").astype("datetime64[D]")
    return sale_day[col(ds, "detalle_ventas", "venta_id").astype(np.int64) - 1]


def branch_id(code: str) -> int:
    return next(b.id for b in cat.BRANCHES if b.codigo == code)


def test_volume_matches_the_spec(ds: Dataset) -> None:
    counts = ds.row_counts()
    assert 480_000 <= counts["detalle_ventas"] <= 520_000
    assert counts["regiones"] == 4
    assert counts["sucursales"] == 24
    assert counts["categorias"] == 10
    assert counts["productos"] > 350
    assert counts["clientes"] == 25_000
    assert counts["devoluciones"] > 3_000
    assert counts["inventario"] > 150_000


def test_generation_is_deterministic() -> None:
    small = GeneratorConfig(scale=0.03, customers=2_000)
    assert generate(small).checksum() == generate(small).checksum()
    assert (
        generate(small).checksum()
        != generate(GeneratorConfig(seed=7, scale=0.03, customers=2_000)).checksum()
    )


def test_primary_keys_are_sequential_and_unique(ds: Dataset) -> None:
    for table, key in [
        ("productos", "producto_id"),
        ("clientes", "cliente_id"),
        ("empleados", "empleado_id"),
        ("ventas", "venta_id"),
        ("detalle_ventas", "detalle_id"),
        ("devoluciones", "devolucion_id"),
    ]:
        ids = col(ds, table, key)
        assert np.array_equal(ids, np.arange(1, len(ids) + 1)), table


def test_foreign_keys_resolve(ds: Dataset) -> None:
    n_products = len(ds.table("productos"))
    n_customers = len(ds.table("clientes"))
    n_employees = len(ds.table("empleados"))
    n_sales = len(ds.table("ventas"))
    customer = col(ds, "ventas", "cliente_id")
    assert ((customer == NULL_INT) | ((customer >= 1) & (customer <= n_customers))).all()
    assert col(ds, "ventas", "empleado_id").max() <= n_employees
    assert col(ds, "detalle_ventas", "producto_id").max() <= n_products
    assert col(ds, "detalle_ventas", "venta_id").max() <= n_sales
    assert set(np.unique(col(ds, "detalle_ventas", "venta_id")).tolist()) == set(
        range(1, n_sales + 1)
    )
    supervisor = col(ds, "empleados", "supervisor_id")
    assert (supervisor == NULL_INT).sum() == 1
    assert col(ds, "inventario", "producto_id").max() <= n_products


def test_sale_amounts_are_consistent(ds: Dataset) -> None:
    v = ds.table("ventas").data
    d = ds.table("detalle_ventas").data
    gross = d["cantidad"].astype(np.int64) * d["precio_unitario"].astype(np.int64)
    idx = d["venta_id"].astype(np.int64) - 1
    subtotal = np.bincount(idx, weights=gross, minlength=len(v["venta_id"]))
    discounts = np.bincount(
        idx, weights=d["descuento"].astype(np.int64), minlength=len(v["venta_id"])
    )
    assert np.array_equal(np.rint(subtotal).astype(np.int64), v["subtotal"])
    assert np.array_equal(np.rint(discounts).astype(np.int64), v["descuento_total"])
    assert np.array_equal(v["total"], v["subtotal"] - v["descuento_total"] + v["iva"])
    assert (d["descuento"] <= gross).all()
    assert (v["iva"] >= 0).all()


def test_iva_is_15_percent_of_taxable_base(ds: Dataset) -> None:
    d = ds.table("detalle_ventas").data
    taxable = ds.table("productos").data["graba_iva"][d["producto_id"].astype(np.int64) - 1]
    net = d["cantidad"].astype(np.int64) * d["precio_unitario"].astype(np.int64) - d[
        "descuento"
    ].astype(np.int64)
    base = np.bincount(d["venta_id"].astype(np.int64) - 1, weights=np.where(taxable, net, 0))
    iva = ds.table("ventas").data["iva"]
    assert np.abs(iva - base * 0.15).max() <= 1  # half-up rounding to the cent


def test_people_have_valid_unique_identifiers(ds: Dataset) -> None:
    for table in ("clientes", "empleados"):
        cedulas = col(ds, table, "cedula").tolist()
        emails = col(ds, table, "email").tolist()
        assert len(set(cedulas)) == len(cedulas)
        assert len(set(emails)) == len(emails)
        assert all(is_valid_cedula(c) for c in cedulas)
    phones = col(ds, "clientes", "telefono").tolist()
    assert all(p.startswith("09") and len(p) == 10 for p in phones)


def test_cedula_validator_rejects_bad_check_digit() -> None:
    assert is_valid_cedula("1710034065")
    assert not is_valid_cedula("1710034066")
    assert not is_valid_cedula("9910034065")
    assert not is_valid_cedula("17100340")


def test_no_sales_before_opening_or_during_closure(ds: Dataset) -> None:
    day = col(ds, "ventas", "fecha_venta").astype("datetime64[D]")
    branch = col(ds, "ventas", "sucursal_id")
    for b in cat.BRANCHES:
        assert (day[branch == b.id] >= np.datetime64(b.fecha_apertura)).all(), b.codigo
    start, end = (np.datetime64(d) for d in cat.CLOSURE_WINDOW)
    closed = branch == branch_id(cat.CLOSURE_BRANCH_CODE)
    assert not ((day >= start) & (day <= end) & closed).any()
    manta = branch == branch_id("MAN-01")
    assert manta.sum() > 1_000


def test_people_exist_before_they_transact(ds: Dataset) -> None:
    day = col(ds, "ventas", "fecha_venta").astype("datetime64[D]")
    customer = col(ds, "ventas", "cliente_id")
    registered = col(ds, "clientes", "fecha_registro")
    known = customer != NULL_INT
    assert (registered[customer[known] - 1] <= day[known]).all()
    hired = col(ds, "empleados", "fecha_ingreso")
    assert (hired[col(ds, "ventas", "empleado_id") - 1] <= day).all()


def test_sales_cover_the_period_and_are_chronological(ds: Dataset) -> None:
    stamp = col(ds, "ventas", "fecha_venta")
    assert stamp.min() >= np.datetime64("2024-11-01")
    assert stamp.max() < np.datetime64("2026-11-01")
    assert (np.diff(stamp.astype(np.int64)) >= 0).all()


def test_planted_stockout(ds: Dataset) -> None:
    products = ds.table("productos").data
    is_tv = np.char.startswith(products["nombre"].astype(str), "Smart TV")
    days = line_days(ds)
    branch = col(ds, "ventas", "sucursal_id")[col(ds, "detalle_ventas", "venta_id") - 1]
    product = col(ds, "detalle_ventas", "producto_id")
    qui02 = branch == branch_id(cat.STOCKOUT_BRANCH_CODE)
    start, end = (np.datetime64(d) for d in cat.STOCKOUT_WINDOW)
    # The stocked-out TV is the best seller among TVs at that branch before the window...
    before = qui02 & (days < start) & is_tv[product - 1]
    top_tv = int(np.bincount(product[before]).argmax())
    # ...and sells nothing there during the window, while other TVs still do.
    window = qui02 & (days >= start) & (days <= end)
    assert not (window & (product == top_tv)).any()
    assert (window & is_tv[product - 1]).any()
    inv = ds.table("inventario").data
    snap = (
        (inv["sucursal_id"] == branch_id(cat.STOCKOUT_BRANCH_CODE))
        & (inv["producto_id"] == top_tv)
        & (inv["fecha_corte"] == np.datetime64("2026-08-31"))
    )
    assert inv["stock"][snap].tolist() == [0]


def test_planted_returns_spike(ds: Dataset) -> None:
    products = ds.table("productos").data
    blender = int(np.nonzero(products["nombre"] == "Licuadora Xpert 10 velocidades")[0][0]) + 1
    returned_lines = col(ds, "devoluciones", "detalle_id") - 1
    returned = np.zeros(len(ds.table("detalle_ventas")), bool)
    returned[returned_lines] = True
    days = line_days(ds)
    is_blender = col(ds, "detalle_ventas", "producto_id") == blender
    start, end = (np.datetime64(d) for d in cat.RETURNS_SPIKE_WINDOW)
    in_window = is_blender & (days >= start) & (days <= end)
    outside = is_blender & ~in_window
    assert returned[in_window].mean() > 0.15
    assert returned[outside].mean() < 0.08


def test_planted_outlier_order(ds: Dataset) -> None:
    d = ds.table("detalle_ventas").data
    big = d["cantidad"] == cat.OUTLIER_ORDER_QUANTITY
    assert big.sum() >= 1
    sale = int(d["venta_id"][big][0]) - 1
    assert str(col(ds, "ventas", "fecha_venta")[sale].astype("datetime64[D]")) == str(
        cat.OUTLIER_ORDER_DATE
    )


def test_voided_sales_and_returns_rules(ds: Dataset) -> None:
    estado = col(ds, "ventas", "estado")
    assert 0.007 < (estado == "anulada").mean() < 0.013
    returned_sale = col(ds, "devoluciones", "venta_id") - 1
    assert (estado[returned_sale] == "completada").all()
    sale_day = col(ds, "ventas", "fecha_venta").astype("datetime64[D]")[returned_sale]
    delay = (col(ds, "devoluciones", "fecha_devolucion") - sale_day).astype(np.int64)
    assert delay.min() >= 1
    assert delay.max() <= 30
    assert col(ds, "devoluciones", "fecha_devolucion").max() <= np.datetime64(date(2026, 10, 31))


def test_seasonality_is_visible(ds: Dataset) -> None:
    month = col(ds, "ventas", "fecha_venta").astype("datetime64[M]")
    per_month = {str(m): int(c) for m, c in zip(*np.unique(month, return_counts=True), strict=True)}
    assert per_month["2025-12"] > 1.25 * per_month["2025-10"]
    assert per_month["2026-01"] < per_month["2025-12"] * 0.7
    # Growth: same month one year later is larger.
    assert per_month["2026-10"] > per_month["2025-10"]


def test_school_supplies_follow_regional_calendars(ds: Dataset) -> None:
    category = ds.table("productos").data["categoria_id"][
        col(ds, "detalle_ventas", "producto_id") - 1
    ]
    utiles = category == next(c.id for c in cat.CATEGORIES if c.nombre == "Útiles Escolares")
    branch = col(ds, "ventas", "sucursal_id")[col(ds, "detalle_ventas", "venta_id") - 1]
    costa_ids = [b.id for b in cat.BRANCHES if b.region_id in (2, 4)]
    costa = np.isin(branch, costa_ids)
    month = line_days(ds).astype("datetime64[M]")

    def share(mask_month: str, region_mask: NDArray[np.bool_]) -> float:
        sel = (month == np.datetime64(mask_month)) & region_mask
        return float(utiles[sel].mean())

    assert share("2025-04", costa) > 2 * share("2025-04", ~costa)
    assert share("2025-08", ~costa) > 2 * share("2025-08", costa)
