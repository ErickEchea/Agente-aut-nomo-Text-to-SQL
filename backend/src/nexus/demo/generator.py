"""Deterministic, vectorized generator for the retail demo dataset (ADR-0017).

Same ``GeneratorConfig`` → byte-identical tables (verified by ``Dataset.checksum``).
"""

from __future__ import annotations

import hashlib
import unicodedata
from dataclasses import dataclass
from datetime import date, timedelta

import numpy as np
from numpy.typing import NDArray

from nexus.demo import DATASET_VERSION
from nexus.demo import catalog as cat
from nexus.demo.calendar import (
    COSTA,
    N_REGIMES,
    SIERRA,
    WORLD_CUP_2026,
    DayFeatures,
    black_friday,
    carnaval,
    category_multipliers,
    day_features,
    online_share,
    school_season,
    ticket_volume,
    years_in,
)
from nexus.demo.tables import NULL_INT, Column, Table

IntArray = NDArray[np.int64]
FloatArray = NDArray[np.float64]
BoolArray = NDArray[np.bool_]

DEDUPE_CORRECTION = 1.006  # merging repeated (ticket, product) lines removes ~0.6 % of raw lines
ONLINE_DAY_HOURS = np.array(
    [1, 1, 1, 1, 1, 1, 2, 3, 4, 5, 6, 6, 6, 5, 5, 5, 6, 7, 8, 9, 9, 8, 5, 3], float
)
STORE_HOURS = np.arange(8, 22)
STORE_HOUR_WEIGHTS = np.array([2, 4, 6, 8, 9, 7, 6, 6, 7, 9, 10, 9, 6, 3], float)
CONSUMIDOR_FINAL_RATE = 0.30
SAME_CITY_RATE = 0.85


DEFAULT_SEED = 20241101
DEFAULT_SCALE = 1.0


@dataclass(frozen=True, slots=True)
class GeneratorConfig:
    seed: int = DEFAULT_SEED
    scale: float = DEFAULT_SCALE
    start: date = date(2024, 11, 1)
    end: date = date(2026, 10, 31)
    target_lines: int = 500_000
    customers: int = 25_000

    def __post_init__(self) -> None:
        if not 0 < self.scale <= 10:
            raise ValueError("scale must be in (0, 10]")
        if self.end <= self.start:
            raise ValueError("end must be after start")


@dataclass(frozen=True, slots=True)
class Dataset:
    config: GeneratorConfig
    tables: tuple[Table, ...]  # in load order (parents first)

    def table(self, name: str) -> Table:
        for table in self.tables:
            if table.name == name:
                return table
        raise KeyError(name)

    def row_counts(self) -> dict[str, int]:
        return {table.name: len(table) for table in self.tables}

    def checksum(self) -> str:
        digest = hashlib.sha256(DATASET_VERSION.encode())
        for table in self.tables:
            table.update_hash(digest)
        return digest.hexdigest()


# -------------------------------------------------------------------------------------------------
# Helpers
# -------------------------------------------------------------------------------------------------


def _day_index(features: DayFeatures, day: date) -> int:
    return int((np.datetime64(day, "D") - features.days[0]).astype(np.int64))


def _sample_rows(rng: np.random.Generator, cdf_rows: FloatArray) -> IntArray:
    """Inverse-CDF sampling where each row has its own cumulative distribution."""
    u: FloatArray = rng.random(int(cdf_rows.shape[0]))
    picks = (u[:, None] > cdf_rows).sum(axis=1)
    return np.asarray(np.minimum(picks, cdf_rows.shape[1] - 1), dtype=np.int64)


def _cdf(weights: FloatArray) -> FloatArray:
    cumulative: FloatArray = np.cumsum(weights, axis=-1, dtype=np.float64)
    return np.asarray(cumulative / cumulative[..., -1:], dtype=np.float64)


def _ascii_slug(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", text)
    stripped = "".join(ch for ch in normalized if not unicodedata.combining(ch))
    return "".join(ch for ch in stripped.lower() if ch.isalnum())


def _cedula_check_digit(first_nine: str) -> int:
    """Ecuadorian cédula modulo-10 check digit (coefficients 2,1,2,1,...)."""
    total = 0
    for i, ch in enumerate(first_nine):
        product = int(ch) * (2 if i % 2 == 0 else 1)
        total += product - 9 if product > 9 else product
    return (10 - total % 10) % 10


def is_valid_cedula(cedula: str) -> bool:
    if len(cedula) != 10 or not cedula.isdigit():
        return False
    province = int(cedula[:2])
    if not (1 <= province <= 24 or province == 30) or int(cedula[2]) > 5:
        return False
    return _cedula_check_digit(cedula[:9]) == int(cedula[9])


def _cedulas(rng: np.random.Generator, province_codes: list[str], taken: set[str]) -> list[str]:
    out: list[str] = []
    for code in province_codes:
        while True:
            body = f"{code}{rng.integers(0, 6)}{rng.integers(0, 1_000_000):06d}"
            candidate = body + str(_cedula_check_digit(body))
            if candidate not in taken:
                taken.add(candidate)
                out.append(candidate)
                break
    return out


def _person_names(rng: np.random.Generator, n: int) -> tuple[list[str], list[str]]:
    female = rng.random(n) < 0.5
    compound = rng.random(n) < 0.25
    first: list[str] = []
    for is_f, is_compound in zip(female.tolist(), compound.tolist(), strict=True):
        pool = cat.FIRST_NAMES_F if is_f else cat.FIRST_NAMES_M
        a = pool[int(rng.integers(0, len(pool)))]
        if is_compound:
            b = pool[int(rng.integers(0, len(pool)))]
            first.append(a if b == a or " " in a else f"{a} {b}")
        else:
            first.append(a)
    s1 = rng.integers(0, len(cat.SURNAMES), n)
    s2 = rng.integers(0, len(cat.SURNAMES), n)
    last = [
        f"{cat.SURNAMES[i]} {cat.SURNAMES[j]}"
        for i, j in zip(s1.tolist(), s2.tolist(), strict=True)
    ]
    return first, last


def _charm_price(raw: float) -> float:
    """Retail price endings: $x.99 above $10, $x.x9 below."""
    if raw >= 10:
        return float(np.floor(raw)) + 0.99
    return round(float(np.floor(raw * 10)) / 10 + 0.09, 2)


def _to_cents(values: FloatArray) -> IntArray:
    return np.rint(values * 100).astype(np.int64)


# -------------------------------------------------------------------------------------------------
# Reference tables
# -------------------------------------------------------------------------------------------------


def _regions_table() -> Table:
    return Table(
        "regiones",
        (Column("region_id", "int"), Column("nombre", "text"), Column("descripcion", "text")),
        {
            "region_id": np.array([r.id for r in cat.REGIONS], np.int64),
            "nombre": np.array([r.nombre for r in cat.REGIONS]),
            "descripcion": np.array([r.descripcion for r in cat.REGIONS]),
        },
    )


def _branches_table() -> Table:
    b = cat.BRANCHES
    return Table(
        "sucursales",
        (
            Column("sucursal_id", "int"),
            Column("codigo", "text"),
            Column("nombre", "text"),
            Column("ciudad", "text"),
            Column("provincia", "text"),
            Column("region_id", "int"),
            Column("formato", "text"),
            Column("metros_cuadrados", "int"),
            Column("fecha_apertura", "date"),
        ),
        {
            "sucursal_id": np.array([x.id for x in b], np.int64),
            "codigo": np.array([x.codigo for x in b]),
            "nombre": np.array([x.nombre for x in b]),
            "ciudad": np.array([x.ciudad for x in b]),
            "provincia": np.array([x.provincia for x in b]),
            "region_id": np.array([x.region_id for x in b], np.int64),
            "formato": np.array([x.formato for x in b]),
            "metros_cuadrados": np.array([x.metros_cuadrados for x in b], np.int64),
            "fecha_apertura": np.array([x.fecha_apertura for x in b], "datetime64[D]"),
        },
    )


def _categories_table() -> Table:
    c = cat.CATEGORIES
    return Table(
        "categorias",
        (Column("categoria_id", "int"), Column("nombre", "text"), Column("descripcion", "text")),
        {
            "categoria_id": np.array([x.id for x in c], np.int64),
            "nombre": np.array([x.nombre for x in c]),
            "descripcion": np.array([x.descripcion for x in c]),
        },
    )


@dataclass(frozen=True, slots=True)
class _Products:
    table: Table
    category: IntArray  # 0-based category index
    price_cents: IntArray  # 2026 list price
    taxable: BoolArray
    launch_day: IntArray  # day index of launch; NULL_INT = always available
    popularity: FloatArray
    tags: tuple[frozenset[str], ...]

    def with_tag(self, tag: str) -> IntArray:
        return np.array([i for i, t in enumerate(self.tags) if tag in t], np.int64)


def _products(rng: np.random.Generator, features: DayFeatures) -> _Products:
    names: list[str] = []
    brands: list[str] = []
    skus: list[str] = []
    cat_idx: list[int] = []
    prices: list[float] = []
    costs: list[float] = []
    taxable: list[bool] = []
    launches: list[date | None] = []
    tags: list[frozenset[str]] = []
    for ci, category in enumerate(cat.CATEGORIES):
        for seq, spec in enumerate(cat.PRODUCTS[category.nombre], start=1):
            price = _charm_price(spec.precio * float(rng.uniform(0.97, 1.03)))
            cost = round(price * category.margin * float(rng.uniform(0.94, 1.04)), 2)
            names.append(spec.nombre)
            brands.append(spec.marca)
            skus.append(f"{category.prefijo}-{seq:04d}")
            cat_idx.append(ci)
            prices.append(price)
            costs.append(cost)
            taxable.append(spec.graba_iva)
            launches.append(spec.lanzamiento)
            tags.append(spec.tags)

    price_arr = np.array(prices)
    staple = np.array(["staple" in t for t in tags])
    popularity = (
        price_arr**-0.35 * rng.lognormal(0.0, 0.45, len(prices)) * np.where(staple, 4.0, 1.0)
    )
    launch_dates = np.array(
        [np.datetime64(d, "D") if d else np.datetime64("NaT", "D") for d in launches],
        "datetime64[D]",
    )
    launch_day = np.array([_day_index(features, d) if d else NULL_INT for d in launches], np.int64)
    n = len(names)
    table = Table(
        "productos",
        (
            Column("producto_id", "int"),
            Column("sku", "text"),
            Column("nombre", "text"),
            Column("marca", "text"),
            Column("categoria_id", "int"),
            Column("precio_lista", "money"),
            Column("costo_unitario", "money"),
            Column("graba_iva", "bool"),
            Column("fecha_lanzamiento", "date", nullable=True),
        ),
        {
            "producto_id": np.arange(1, n + 1, dtype=np.int64),
            "sku": np.array(skus),
            "nombre": np.array(names),
            "marca": np.array(brands),
            "categoria_id": np.array(cat_idx, np.int64) + 1,
            "precio_lista": _to_cents(price_arr),
            "costo_unitario": _to_cents(np.array(costs)),
            "graba_iva": np.array(taxable, np.bool_),
            "fecha_lanzamiento": launch_dates,
        },
    )
    return _Products(
        table=table,
        category=np.array(cat_idx, np.int64),
        price_cents=_to_cents(price_arr),
        taxable=np.array(taxable, np.bool_),
        launch_day=launch_day,
        popularity=popularity,
        tags=tuple(tags),
    )


# -------------------------------------------------------------------------------------------------
# Branch traffic
# -------------------------------------------------------------------------------------------------


def _branch_arrays() -> tuple[IntArray, FloatArray, FloatArray]:
    regions = {r.id: r for r in cat.REGIONS}
    regime = np.array([regions[b.region_id].regime for b in cat.BRANCHES], np.int64)
    growth = np.array([regions[b.region_id].annual_growth for b in cat.BRANCHES])
    fmt = np.array([cat.FORMAT_TRAFFIC[b.formato] for b in cat.BRANCHES])
    return regime, growth, fmt


def _branch_index(code: str) -> int:
    return next(i for i, b in enumerate(cat.BRANCHES) if b.codigo == code)


def _traffic(rng: np.random.Generator, features: DayFeatures) -> FloatArray:
    """Relative expected tickets per (day, branch)."""
    regime, growth, fmt = _branch_arrays()
    by_regime = ticket_volume(features)
    traffic = by_regime[:, regime]
    traffic *= (1.0 + growth[None, :]) ** features.years_elapsed[:, None]
    traffic *= fmt[None, :] * rng.lognormal(0.0, 0.12, len(cat.BRANCHES))[None, :]

    days = features.days
    for bi, branch in enumerate(cat.BRANCHES):
        opening = np.datetime64(branch.fecha_apertura, "D")
        traffic[:, bi] *= days >= opening
        # New stores ramp up over 60 days.
        age = (days - opening).astype(np.int64)
        traffic[:, bi] *= np.where((age >= 0) & (age < 60), 0.6 + 0.4 * age / 60, 1.0)

    for year in years_in(features):
        quito = [i for i, b in enumerate(cat.BRANCHES) if b.ciudad == "Quito"]
        fiestas = (days >= np.datetime64(date(year, 12, 1))) & (
            days <= np.datetime64(date(year, 12, 6))
        )
        traffic[np.ix_(fiestas, quito)] *= 1.10
        guayaquil = [i for i, b in enumerate(cat.BRANCHES) if b.ciudad == "Guayaquil"]
        fundacion = days == np.datetime64(date(year, 7, 25))
        traffic[np.ix_(fundacion, guayaquil)] *= 1.10

    closed = _branch_index(cat.CLOSURE_BRANCH_CODE)
    c_start, c_end = (np.datetime64(d, "D") for d in cat.CLOSURE_WINDOW)
    traffic[(days >= c_start) & (days <= c_end), closed] = 0.0
    return traffic


# -------------------------------------------------------------------------------------------------
# People
# -------------------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _Customers:
    table: Table
    segment: IntArray  # index into cat.SEGMENTS, by customer row (id - 1)
    city_names: tuple[str, ...]
    # Per city: customer rows sorted by registration day, their registration days and
    # cumulative purchase weights.
    by_city: tuple[tuple[IntArray, IntArray, FloatArray], ...]
    city_weights: FloatArray


def _customers(
    rng: np.random.Generator, config: GeneratorConfig, traffic: FloatArray
) -> _Customers:
    n = max(500, round(config.customers * config.scale))
    cities = tuple(dict.fromkeys(b.ciudad for b in cat.BRANCHES))
    province_of = {b.ciudad: b.provincia for b in cat.BRANCHES}
    first_open = {
        city: min(b.fecha_apertura for b in cat.BRANCHES if b.ciudad == city) for city in cities
    }
    volume = traffic.sum(axis=0)
    city_weights = np.array(
        [sum(volume[i] for i, b in enumerate(cat.BRANCHES) if b.ciudad == c) for c in cities]
    )
    city_weights = city_weights / city_weights.sum()
    city_of = rng.choice(len(cities), size=n, p=city_weights)

    start_ord = config.start.toordinal()
    end_ord = config.end.toordinal()
    reg_ord = np.empty(n, np.int64)
    before = rng.random(n) < 0.55
    reg_ord[before] = rng.integers(date(2016, 1, 1).toordinal(), start_ord, before.sum())
    # Registrations during the period grow over time (triangular density toward the end).
    during = ~before
    reg_ord[during] = np.floor(rng.triangular(start_ord, end_ord, end_ord, during.sum())).astype(
        np.int64
    )
    for ci, city in enumerate(cities):
        opening = first_open[city].toordinal()
        if opening > start_ord:
            members = city_of == ci
            reg_ord[members] = rng.integers(opening - 15, end_ord + 1, members.sum())
    reg_ord = np.minimum(reg_ord, end_ord)

    order = np.lexsort((np.arange(n), reg_ord))
    city_of = city_of[order]
    reg_ord = reg_ord[order]

    segment = rng.choice(len(cat.SEGMENTS), size=n, p=cat.SEGMENT_SHARES)
    first, last = _person_names(rng, n)
    cedulas = _cedulas(rng, [cat.PROVINCE_CODES[province_of[cities[c]]] for c in city_of], set())
    phones = [f"09{v:08d}" for v in rng.integers(0, 100_000_000, n).tolist()]
    domains = rng.integers(0, len(cat.EMAIL_DOMAINS), n)
    suffix = rng.integers(1, 100, n)
    emails: list[str] = []
    seen: set[str] = set()
    for i in range(n):
        local = f"{_ascii_slug(first[i].split()[0])}.{_ascii_slug(last[i].split()[0])}{suffix[i]}"
        email = f"{local}@{cat.EMAIL_DOMAINS[domains[i]]}"
        if email in seen:
            email = f"{local}.{i + 1}@{cat.EMAIL_DOMAINS[domains[i]]}"
        seen.add(email)
        emails.append(email)
    age_days = np.clip(rng.normal(40, 13, n), 18, 80) * 365.25
    birth = np.datetime64(config.start, "D") - age_days.astype(np.int64).astype("timedelta64[D]")

    reg_day = reg_ord - start_ord  # negative = registered before the period
    weights = np.array(cat.SEGMENT_PURCHASE_WEIGHT)[segment]
    by_city = []
    for ci in range(len(cities)):
        rows = np.nonzero(city_of == ci)[0].astype(np.int64)
        by_city.append((rows, reg_day[rows], np.cumsum(weights[rows])))

    table = Table(
        "clientes",
        (
            Column("cliente_id", "int"),
            Column("cedula", "text"),
            Column("nombres", "text"),
            Column("apellidos", "text"),
            Column("email", "text"),
            Column("telefono", "text"),
            Column("fecha_nacimiento", "date"),
            Column("ciudad", "text"),
            Column("provincia", "text"),
            Column("segmento", "text"),
            Column("fecha_registro", "date"),
        ),
        {
            "cliente_id": np.arange(1, n + 1, dtype=np.int64),
            "cedula": np.array(cedulas),
            "nombres": np.array(first),
            "apellidos": np.array(last),
            "email": np.array(emails),
            "telefono": np.array(phones),
            "fecha_nacimiento": birth.astype("datetime64[D]"),
            "ciudad": np.array([cities[c] for c in city_of]),
            "provincia": np.array([province_of[cities[c]] for c in city_of]),
            "segmento": np.array([cat.SEGMENTS[s] for s in segment]),
            "fecha_registro": (reg_ord - date(1970, 1, 1).toordinal()).astype("datetime64[D]"),
        },
    )
    return _Customers(table, segment.astype(np.int64), cities, tuple(by_city), city_weights)


@dataclass(frozen=True, slots=True)
class _Employees:
    table: Table
    # Per branch: selling-staff employee ids sorted by hire day, and their hire days.
    sellers: tuple[tuple[IntArray, IntArray], ...]


def _employees(rng: np.random.Generator, config: GeneratorConfig) -> _Employees:
    roles: list[str] = []
    branch_ids: list[int] = []
    supervisors: list[int] = []
    hire: list[date] = []
    regional_branch = {1: "QUI-02", 2: "GYE-01", 3: "PUY-01", 4: "GAL-01"}
    start_ord = config.start.toordinal()

    def add(role: str, branch: cat.Branch, supervisor: int, hired: date) -> int:
        roles.append(role)
        branch_ids.append(branch.id)
        supervisors.append(supervisor)
        hire.append(hired)
        return len(roles)  # 1-based employee id

    def hire_date(branch: cat.Branch, senior: bool) -> date:
        if branch.fecha_apertura.toordinal() > start_ord:
            lo = branch.fecha_apertura.toordinal() - 45
            return date.fromordinal(int(rng.integers(lo, branch.fecha_apertura.toordinal())))
        lo = max(branch.fecha_apertura.toordinal(), date(2012, 1, 1).toordinal())
        if not senior and rng.random() < 0.15:
            return date.fromordinal(int(rng.integers(start_ord, config.end.toordinal())))
        return date.fromordinal(int(rng.integers(lo, start_ord)))

    by_code = {b.codigo: b for b in cat.BRANCHES}
    general = add("gerente general", by_code["QUI-02"], NULL_INT, date(2009, 8, 1))
    regional = {
        region_id: add("gerente regional", by_code[code], general, hire_date(by_code[code], True))
        for region_id, code in regional_branch.items()
    }
    for branch in cat.BRANCHES:
        plan = cat.STAFF_PLAN[branch.formato]
        manager = add(
            "gerente de sucursal", branch, regional[branch.region_id], hire_date(branch, True)
        )
        sups = [
            add("supervisor", branch, manager, hire_date(branch, True))
            for _ in range(plan["supervisor"])
        ]
        k = 0
        for role in ("cajero", "vendedor", "bodeguero"):
            for _ in range(plan[role]):
                # The first cashier is on staff before the period, so every sale has a seller.
                add(role, branch, sups[k % len(sups)], hire_date(branch, senior=k == 0))
                k += 1

    n = len(roles)
    first, last = _person_names(rng, n)
    province = {b.id: b.provincia for b in cat.BRANCHES}
    cedulas = _cedulas(rng, [cat.PROVINCE_CODES[province[b]] for b in branch_ids], set())
    salaries = np.array(
        [
            int(rng.integers(cat.SALARY_RANGES[r][0] // 5, cat.SALARY_RANGES[r][1] // 5 + 1)) * 5
            for r in roles
        ],
        np.int64,
    )
    emails: list[str] = []
    seen: set[str] = set()
    for i in range(n):
        local = f"{_ascii_slug(first[i].split()[0])}.{_ascii_slug(last[i].split()[0])}"
        candidate, k = local, 1
        while candidate in seen:
            k += 1
            candidate = f"{local}{k}"
        seen.add(candidate)
        emails.append(f"{candidate}@{cat.CORPORATE_EMAIL_DOMAIN}")

    hire_arr = np.array(hire, "datetime64[D]")
    hire_day = (hire_arr - np.datetime64(config.start, "D")).astype(np.int64)
    ids = np.arange(1, n + 1, dtype=np.int64)
    branch_arr = np.array(branch_ids, np.int64)
    selling = np.isin(np.array(roles), cat.SELLING_ROLES)
    sellers = []
    for branch in cat.BRANCHES:
        mask = selling & (branch_arr == branch.id)
        order = np.argsort(hire_day[mask], kind="stable")
        sellers.append((ids[mask][order], hire_day[mask][order]))

    table = Table(
        "empleados",
        (
            Column("empleado_id", "int"),
            Column("cedula", "text"),
            Column("nombres", "text"),
            Column("apellidos", "text"),
            Column("email", "text"),
            Column("cargo", "text"),
            Column("sucursal_id", "int"),
            Column("supervisor_id", "int", nullable=True),
            Column("fecha_ingreso", "date"),
            Column("salario_mensual", "money"),
        ),
        {
            "empleado_id": ids,
            "cedula": np.array(cedulas),
            "nombres": np.array(first),
            "apellidos": np.array(last),
            "email": np.array(emails),
            "cargo": np.array(roles),
            "sucursal_id": branch_arr,
            "supervisor_id": np.array(supervisors, np.int64),
            "fecha_ingreso": hire_arr,
            "salario_mensual": salaries * 100,
        },
    )
    return _Employees(table, tuple(sellers))


# -------------------------------------------------------------------------------------------------
# Product demand by month
# -------------------------------------------------------------------------------------------------


def _month_school_intensity(features: DayFeatures) -> FloatArray:
    """Mean back-to-school intensity per (month_index, regime)."""
    school = school_season(features)
    months = int(features.month_index.max()) + 1
    out = np.zeros((months, N_REGIMES))
    counts = np.bincount(features.month_index, minlength=months).astype(float)
    for r in range(N_REGIMES):
        out[:, r] = (
            np.bincount(features.month_index, weights=school[:, r], minlength=months) / counts
        )
    return out


def _product_month_weights(features: DayFeatures, products: _Products) -> FloatArray:
    """Product demand weights per (month_index, regime, product)."""
    months = int(features.month_index.max()) + 1
    first_day_of_month = np.array(
        [int(np.nonzero(features.month_index == m)[0][0]) for m in range(months)], np.int64
    )
    last_day_of_month = np.array(
        [int(np.nonzero(features.month_index == m)[0][-1]) for m in range(months)], np.int64
    )
    month_num = features.month[first_day_of_month]
    year = features.year[first_day_of_month]
    school = _month_school_intensity(features)

    w = np.broadcast_to(products.popularity, (months, N_REGIMES, len(products.popularity))).copy()
    available = (products.launch_day == NULL_INT)[None, :] | (
        products.launch_day[None, :] <= last_day_of_month[:, None]
    )
    w *= available[:, None, :]

    factors = _tag_factors(features, month_num, year, school)
    for p, tags in enumerate(products.tags):
        # Fixed tag order (not frozenset iteration order, which depends on hash randomization).
        for tag in factors:
            if tag in tags:
                w[:, :, p] *= factors[tag]
    return w


def _regional(sierra: FloatArray | float, costa: FloatArray | float, months: int) -> FloatArray:
    out = np.empty((months, N_REGIMES))
    out[:, SIERRA] = sierra
    out[:, COSTA] = costa
    return out


def _tag_factors(
    features: DayFeatures, month_num: IntArray, year: IntArray, school: FloatArray
) -> dict[str, FloatArray]:
    """Demand multiplier per (month_index, regime) for each product tag, in application order."""
    months = len(month_num)
    carnival_months = {(d.year, d.month) for y in years_in(features) for d in carnaval(y)}
    carnival_hit = np.array(
        [(y, m) in carnival_months for y, m in zip(year, month_num, strict=True)]
    )
    wc_start, wc_end = WORLD_CUP_2026
    in_wc = (year == wc_start.year) & (month_num >= wc_start.month) & (month_num <= wc_end.month)
    pre_wc = (year == wc_start.year) & (month_num == wc_start.month - 1)
    tv_wc = (year == wc_start.year) & np.isin(month_num, (5, 6))
    ones = np.ones((months, N_REGIMES))
    return {
        "fitness": ones * np.select([month_num == 1, month_num == 2], [3.0, 1.6], 1.0)[:, None],
        "carnaval": ones * np.where(carnival_hit, 6.0, 0.8)[:, None],
        "worldcup": ones * np.select([in_wc, pre_wc], [8.0, 2.5], 0.7)[:, None],
        "tv": ones * np.where(tv_wc, 1.6, 1.0)[:, None],
        "cooling": _regional(0.35, np.where(month_num <= 5, 2.0, 1.0), months),
        "warm": _regional(np.where(np.isin(month_num, (6, 7, 8)), 1.9, 1.6), 0.4, months),
        "sun": _regional(0.7, np.where(month_num <= 4, 2.5, 1.8), months),
        "club_costa": _regional(0.3, 2.5, months),
        "club_sierra": _regional(2.5, 0.3, months),
        "school_uniform": 1.0 + 6.0 * school,
        "laptop": 1.0 + 1.0 * school,
    }


# -------------------------------------------------------------------------------------------------
# Sales simulation
# -------------------------------------------------------------------------------------------------


@dataclass(frozen=True, slots=True)
class _Sales:
    ventas: Table
    detalle: Table
    line_day: IntArray
    line_branch: IntArray  # 0-based
    line_product: IntArray  # 0-based
    line_qty: IntArray
    line_net_cents: IntArray
    line_category: IntArray
    line_completed: BoolArray


@dataclass(frozen=True, slots=True)
class _Context:
    rng: np.random.Generator
    config: GeneratorConfig
    features: DayFeatures
    traffic: FloatArray
    products: _Products
    customers: _Customers
    employees: _Employees


@dataclass(slots=True)
class _Tickets:
    """One entry per ticket (sale header), in generation order."""

    day: IntArray
    branch: IntArray
    online: BoolArray
    seconds: IntArray
    voided: BoolArray
    payment: IntArray
    customer: IntArray
    employee: IntArray

    @property
    def n(self) -> int:
        return len(self.day)


@dataclass(slots=True)
class _Lines:
    ticket: IntArray
    product: IntArray
    qty: IntArray


def _extra_lines(features: DayFeatures) -> FloatArray:
    """Expected extra lines per ticket beyond the first, per (day, branch)."""
    is_hyper = np.array([b.formato == "hipermercado" for b in cat.BRANCHES])
    december = (features.month == 12)[:, None]
    return np.asarray(1.3 + 0.5 * is_hyper[None, :] + 0.3 * december, dtype=np.float64)


def _assign_customers(
    ctx: _Context, day: IntArray, branch: IntArray, online: BoolArray
) -> IntArray:
    """Consumidor final (NULL) for part of in-store tickets; mostly customers of the same city."""
    rng, customers = ctx.rng, ctx.customers
    n = len(day)
    customer = np.full(n, NULL_INT, np.int64)
    identified = online | (rng.random(n) >= CONSUMIDOR_FINAL_RATE)
    branch_city = np.array([customers.city_names.index(b.ciudad) for b in cat.BRANCHES], np.int64)
    same_city = rng.random(n) < SAME_CITY_RATE
    any_city = rng.choice(len(customers.city_names), n, p=customers.city_weights)
    city = np.where(same_city, branch_city[branch], any_city)
    u = rng.random(n)
    for ci, (rows, reg_day, cumw) in enumerate(customers.by_city):
        sel = np.nonzero(identified & (city == ci))[0]
        if len(sel) == 0 or len(rows) == 0:
            continue
        eligible = np.searchsorted(reg_day, day[sel], side="right")
        ok = eligible > 0
        target = u[sel[ok]] * cumw[eligible[ok] - 1]
        pick = np.minimum(np.searchsorted(cumw, target, side="right"), eligible[ok] - 1)
        customer[sel[ok]] = rows[pick] + 1
    return customer


def _assign_employees(ctx: _Context, day: IntArray, branch: IntArray) -> IntArray:
    """A seller (cashier or salesperson) of the branch already hired on the sale day."""
    employee = np.empty(len(day), np.int64)
    u = ctx.rng.random(len(day))
    for bi, (emp_ids, hire_day) in enumerate(ctx.employees.sellers):
        sel = np.nonzero(branch == bi)[0]
        if len(sel) == 0:
            continue
        eligible = np.maximum(np.searchsorted(hire_day, day[sel], side="right"), 1)
        employee[sel] = emp_ids[np.floor(u[sel] * eligible).astype(np.int64)]
    return employee


def _simulate_tickets(ctx: _Context, extra_lines: FloatArray, share_online: FloatArray) -> _Tickets:
    rng, features, traffic = ctx.rng, ctx.features, ctx.traffic
    n_days, n_branches = traffic.shape
    expected_lines = (traffic * (1.0 + extra_lines + 0.8 * share_online[:, None])).sum()
    k = ctx.config.target_lines * ctx.config.scale * DEDUPE_CORRECTION / expected_lines
    counts = rng.poisson(traffic * k)

    flat = np.repeat(np.arange(n_days * n_branches), counts.ravel())
    day = (flat // n_branches).astype(np.int64)
    branch = (flat % n_branches).astype(np.int64)
    n = len(day)

    online = rng.random(n) < share_online[day]
    store_cdf = np.broadcast_to(_cdf(STORE_HOUR_WEIGHTS), (n, len(STORE_HOURS)))
    store_hour = STORE_HOURS[_sample_rows(rng, store_cdf)]
    online_hour = _sample_rows(rng, np.broadcast_to(_cdf(ONLINE_DAY_HOURS), (n, 24)))
    seconds = np.where(online, online_hour, store_hour) * 3600 + rng.integers(0, 3600, n)
    voided = rng.random(n) < cat.VOID_RATE

    # Payment method shares drift over the period; online orders never pay cash.
    frac = (features.years_elapsed / features.years_elapsed[-1])[day]
    start = np.array(cat.PAYMENT_SHARES_START)
    end = np.array(cat.PAYMENT_SHARES_END)
    pay_w = start[None, :] + frac[:, None] * (end - start)[None, :]
    pay_w[online, 0] = 0.0
    payment = _sample_rows(rng, _cdf(pay_w))

    return _Tickets(
        day=day,
        branch=branch,
        online=online,
        seconds=seconds.astype(np.int64),
        voided=voided,
        payment=payment,
        customer=_assign_customers(ctx, day, branch, online),
        employee=_assign_employees(ctx, day, branch),
    )


def _sample_products(
    ctx: _Context, line_category: IntArray, day: IntArray, regime: IntArray
) -> IntArray:
    """Product per line from month- and regime-dependent weights within its category."""
    month_w = _product_month_weights(ctx.features, ctx.products)
    month = ctx.features.month_index[day]
    product = np.empty(len(line_category), np.int64)
    for ci in range(len(cat.CATEGORIES)):
        members = np.nonzero(ctx.products.category == ci)[0]
        lines = np.nonzero(line_category == ci)[0]
        group = month[lines] * N_REGIMES + regime[lines]
        order = np.argsort(group, kind="stable")
        lines, group = lines[order], group[order]
        bounds = np.flatnonzero(np.diff(group)) + 1
        for chunk in np.split(np.arange(len(lines)), bounds):
            if len(chunk) == 0:
                continue
            g = int(group[chunk[0]])
            weights = month_w[g // N_REGIMES, g % N_REGIMES, members]
            product[lines[chunk]] = ctx.rng.choice(
                members, size=len(chunk), p=weights / weights.sum()
            )
    return product


def _corporate_ids(customers: _Customers) -> IntArray:
    corporate = customers.segment == cat.SEGMENTS.index("corporativo")
    return np.asarray(np.nonzero(corporate)[0] + 1, dtype=np.int64)


def _simulate_lines(ctx: _Context, tickets: _Tickets, extra_lines: FloatArray) -> _Lines:
    rng, features = ctx.rng, ctx.features
    regime, _, _ = _branch_arrays()
    lam = extra_lines[tickets.day, tickets.branch] + 0.8 * tickets.online
    n_lines = np.minimum(1 + rng.poisson(lam), 15)
    ticket = np.repeat(np.arange(tickets.n, dtype=np.int64), n_lines)
    day = tickets.day[ticket]
    line_regime = regime[tickets.branch[ticket]]

    cat_names = [c.nombre for c in cat.CATEGORIES]
    shares = np.array([c.share for c in cat.CATEGORIES])
    cat_w = category_multipliers(features, cat_names) * shares[None, None, :]
    cat_cdf = _cdf(cat_w).reshape(features.n * N_REGIMES, len(cat_names))
    category = _sample_rows(rng, cat_cdf[day * N_REGIMES + line_regime])
    product = _sample_products(ctx, category, day, line_regime)

    qty_mean = np.array([c.qty_extra_mean for c in cat.CATEGORIES])
    qty = 1 + rng.poisson(qty_mean[category])
    corporate = np.isin(tickets.customer, _corporate_ids(ctx.customers))
    qty = np.where(corporate[ticket], qty * (1 + rng.poisson(1.5, len(qty))), qty)
    return _Lines(ticket=ticket, product=product, qty=qty.astype(np.int64))


def _apply_stockout(ctx: _Context, tickets: _Tickets, lines: _Lines) -> None:
    """Planted stock-out: the top TV vanishes from one Quito branch; shoppers substitute."""
    products = ctx.products
    tvs = products.with_tag("tv")
    tv_rank = tvs[np.argsort(-products.popularity[tvs], kind="stable")]
    top_tv, substitute_tv = int(tv_rank[0]), int(tv_rank[1])
    so_branch = _branch_index(cat.STOCKOUT_BRANCH_CODE)
    so_lo, so_hi = (_day_index(ctx.features, d) for d in cat.STOCKOUT_WINDOW)
    day = tickets.day[lines.ticket]
    stockout = (
        (lines.product == top_tv)
        & (tickets.branch[lines.ticket] == so_branch)
        & (day >= so_lo)
        & (day <= so_hi)
    )
    lines.product[stockout] = substitute_tv


def _append_outlier(ctx: _Context, tickets: _Tickets, lines: _Lines) -> int:
    """Planted outlier: one corporate bulk order of laptops. Returns the new ticket index."""
    customers = ctx.customers
    branch = _branch_index(cat.OUTLIER_ORDER_BRANCH_CODE)
    day = _day_index(ctx.features, cat.OUTLIER_ORDER_DATE)
    city = customers.city_names.index(cat.BRANCHES[branch].ciudad)
    rows, reg_day, _ = customers.by_city[city]
    corporate = rows[(customers.segment[rows] == 2) & (reg_day <= day)]
    if len(corporate) == 0:  # tiny test scales: fall back to any eligible customer of the city
        corporate = rows[reg_day <= day]
    sellers, _ = ctx.employees.sellers[branch]
    index = tickets.n
    tickets.day = np.append(tickets.day, day)
    tickets.branch = np.append(tickets.branch, branch)
    tickets.online = np.append(tickets.online, False)
    tickets.seconds = np.append(tickets.seconds, 11 * 3600 + 7 * 60)
    tickets.voided = np.append(tickets.voided, False)
    tickets.payment = np.append(tickets.payment, cat.PAYMENT_METHODS.index("transferencia"))
    tickets.customer = np.append(tickets.customer, int(corporate[0]) + 1)
    tickets.employee = np.append(tickets.employee, int(sellers[0]))
    lines.ticket = np.append(lines.ticket, index)
    lines.product = np.append(lines.product, int(ctx.products.with_tag("corporate_laptop")[0]))
    lines.qty = np.append(lines.qty, cat.OUTLIER_ORDER_QUANTITY)
    return index


def _merge_lines(lines: _Lines, n_products: int) -> _Lines:
    """Merge repeated (ticket, product) pairs into one line, summing quantities."""
    key = lines.ticket * n_products + lines.product
    unique_key, inverse = np.unique(key, return_inverse=True)
    qty = np.bincount(inverse, weights=lines.qty).astype(np.int64)
    return _Lines(ticket=unique_key // n_products, product=unique_key % n_products, qty=qty)


def _unit_prices(ctx: _Context, tickets: _Tickets, lines: _Lines) -> IntArray:
    """List price deflated by the annual increase, plus the Galápagos surcharge. In cents."""
    day = tickets.day[lines.ticket]
    years_before_2026 = 2026 - ctx.features.year[day]
    insular = np.array([b.region_id == 4 for b in cat.BRANCHES])[tickets.branch[lines.ticket]]
    deflator = (1 + cat.ANNUAL_PRICE_INCREASE) ** years_before_2026
    unit = ctx.products.price_cents[lines.product] / deflator
    unit = np.where(insular, unit * cat.INSULAR_PRICE_SURCHARGE, unit)
    return np.rint(unit).astype(np.int64)


def _discount_rates(ctx: _Context, tickets: _Tickets, lines: _Lines, outlier: int) -> FloatArray:
    """Promotions: Black Friday, Cyber Monday, Christmas, random promos, corporate agreements."""
    rng = ctx.rng
    category = ctx.products.category[lines.product]
    days = ctx.features.days[tickets.day[lines.ticket]]
    online = tickets.online[lines.ticket]
    n = len(lines.ticket)
    rate = np.zeros(n)
    electronics = np.isin(category, (0, 1))
    for year in years_in(ctx.features):
        bf = black_friday(year)
        bf_window = (days >= np.datetime64(bf)) & (days <= np.datetime64(bf + timedelta(days=2)))
        rate = np.where(bf_window & electronics, rng.uniform(0.15, 0.30, n), rate)
        rate = np.where(bf_window & ~electronics & (rng.random(n) < 0.5), 0.10, rate)
        cyber = days == np.datetime64(bf + timedelta(days=3))
        rate = np.where(cyber & online & electronics, np.maximum(rate, 0.15), rate)
        xmas_start = np.datetime64(date(year, 12, 15))
        xmas_end = np.datetime64(date(year, 12, 24))
        xmas = (days >= xmas_start) & (days <= xmas_end)
        xmas_promo = xmas & np.isin(category, (5, 7)) & (rng.random(n) < 0.4)
        rate = np.where(xmas_promo, np.maximum(rate, 0.10), rate)
    promo = rng.random(n) < 0.06
    rate = np.where(promo, np.maximum(rate, rng.choice([0.05, 0.10, 0.15, 0.20], n)), rate)
    corporate = np.isin(tickets.customer, _corporate_ids(ctx.customers))
    rate = np.where(corporate[lines.ticket], np.maximum(rate, 0.05), rate)
    return np.asarray(np.where(lines.ticket == outlier, 0.08, rate), dtype=np.float64)


def _ventas_table(
    tickets: _Tickets,
    stamp: NDArray[np.datetime64],
    order: IntArray,
    amounts: tuple[IntArray, IntArray, IntArray, IntArray],
) -> Table:
    subtotal, discount_total, iva, total = amounts
    return Table(
        "ventas",
        (
            Column("venta_id", "int"),
            Column("fecha_venta", "timestamp"),
            Column("sucursal_id", "int"),
            Column("cliente_id", "int", nullable=True),
            Column("empleado_id", "int"),
            Column("canal", "text"),
            Column("metodo_pago", "text"),
            Column("estado", "text"),
            Column("subtotal", "money"),
            Column("descuento_total", "money"),
            Column("iva", "money"),
            Column("total", "money"),
        ),
        {
            "venta_id": np.arange(1, tickets.n + 1, dtype=np.int64),
            "fecha_venta": stamp[order],
            "sucursal_id": tickets.branch[order] + 1,
            "cliente_id": tickets.customer[order],
            "empleado_id": tickets.employee[order],
            "canal": np.where(tickets.online, "online", "tienda")[order],
            "metodo_pago": np.array(cat.PAYMENT_METHODS)[tickets.payment][order],
            "estado": np.where(tickets.voided, "anulada", "completada")[order],
            "subtotal": subtotal[order],
            "descuento_total": discount_total[order],
            "iva": iva[order],
            "total": total[order],
        },
    )


def _assemble_sales(
    ctx: _Context, tickets: _Tickets, lines: _Lines, unit_cents: IntArray, discount: IntArray
) -> _Sales:
    n_t = tickets.n
    gross = lines.qty * unit_cents
    net = gross - discount
    taxable_net = np.where(ctx.products.taxable[lines.product], net, 0)
    subtotal = np.rint(np.bincount(lines.ticket, weights=gross, minlength=n_t)).astype(np.int64)
    discount_total = np.rint(np.bincount(lines.ticket, weights=discount, minlength=n_t))
    discount_total = discount_total.astype(np.int64)
    taxable_base = np.bincount(lines.ticket, weights=taxable_net, minlength=n_t)
    iva = np.floor(taxable_base * cat.IVA_RATE + 0.5).astype(np.int64)
    total = subtotal - discount_total + iva

    # Chronological ids for sales, then lines ordered by (sale, product).
    seconds = tickets.seconds.astype("timedelta64[s]")
    stamp = ctx.features.days[tickets.day].astype("datetime64[s]") + seconds
    order = np.lexsort((tickets.branch, stamp.astype(np.int64)))
    new_id = np.empty(n_t, np.int64)
    new_id[order] = np.arange(1, n_t + 1)
    line_venta = new_id[lines.ticket]
    line_order = np.lexsort((lines.product, line_venta))

    n_l = len(line_order)
    detalle = Table(
        "detalle_ventas",
        (
            Column("detalle_id", "int"),
            Column("venta_id", "int"),
            Column("producto_id", "int"),
            Column("cantidad", "int"),
            Column("precio_unitario", "money"),
            Column("descuento", "money"),
        ),
        {
            "detalle_id": np.arange(1, n_l + 1, dtype=np.int64),
            "venta_id": line_venta[line_order],
            "producto_id": lines.product[line_order] + 1,
            "cantidad": lines.qty[line_order],
            "precio_unitario": unit_cents[line_order],
            "descuento": discount[line_order],
        },
    )
    return _Sales(
        ventas=_ventas_table(tickets, stamp, order, (subtotal, discount_total, iva, total)),
        detalle=detalle,
        line_day=tickets.day[lines.ticket][line_order],
        line_branch=tickets.branch[lines.ticket][line_order],
        line_product=lines.product[line_order],
        line_qty=lines.qty[line_order],
        line_net_cents=net[line_order],
        line_category=ctx.products.category[lines.product][line_order],
        line_completed=~tickets.voided[lines.ticket][line_order],
    )


def _simulate_sales(ctx: _Context) -> _Sales:
    extra_lines = _extra_lines(ctx.features)
    tickets = _simulate_tickets(ctx, extra_lines, online_share(ctx.features))
    lines = _simulate_lines(ctx, tickets, extra_lines)
    _apply_stockout(ctx, tickets, lines)
    outlier = _append_outlier(ctx, tickets, lines)
    lines = _merge_lines(lines, len(ctx.products.popularity))
    unit_cents = _unit_prices(ctx, tickets, lines)
    rate = _discount_rates(ctx, tickets, lines, outlier)
    discount = np.rint(lines.qty * unit_cents * rate).astype(np.int64)
    return _assemble_sales(ctx, tickets, lines, unit_cents, discount)


# -------------------------------------------------------------------------------------------------
# Returns and inventory
# -------------------------------------------------------------------------------------------------


def _returns(
    rng: np.random.Generator, features: DayFeatures, sales: _Sales, products: _Products
) -> Table:
    rates = np.array([c.return_rate for c in cat.CATEGORIES])[sales.line_category]
    defective = np.isin(sales.line_product, products.with_tag("defective_batch"))
    lo, hi = (_day_index(features, d) for d in cat.RETURNS_SPIKE_WINDOW)
    spike = defective & (sales.line_day >= lo) & (sales.line_day <= hi)
    rates = np.where(spike, cat.RETURNS_SPIKE_RATE, rates)
    returned = sales.line_completed & (rng.random(len(rates)) < rates)

    delay = 1 + np.minimum(rng.geometric(0.12, len(rates)) - 1, 29)
    return_day = sales.line_day + delay
    returned &= return_day < features.n
    idx = np.nonzero(returned)[0]

    reason_w = np.tile(np.array([0.30, 0.20, 0.35, 0.05, 0.10]), (len(idx), 1))
    clothing = sales.line_category[idx] == 5
    reason_w[clothing] = np.array([0.10, 0.05, 0.25, 0.55, 0.05])
    reason = _sample_rows(rng, _cdf(reason_w))
    reason = np.where(spike[idx], 0, reason)

    order = np.lexsort((idx, return_day[idx]))
    idx, reason = idx[order], reason[order]
    detalle_ids = idx + 1
    n = len(idx)
    return Table(
        "devoluciones",
        (
            Column("devolucion_id", "int"),
            Column("detalle_id", "int"),
            Column("venta_id", "int"),
            Column("fecha_devolucion", "date"),
            Column("cantidad", "int"),
            Column("motivo", "text"),
            Column("monto_reembolsado", "money"),
        ),
        {
            "devolucion_id": np.arange(1, n + 1, dtype=np.int64),
            "detalle_id": detalle_ids,
            "venta_id": sales.detalle.data["venta_id"][idx].astype(np.int64),
            "fecha_devolucion": features.days[return_day[idx]],
            "cantidad": sales.line_qty[idx],
            "motivo": np.array(cat.RETURN_REASONS)[reason],
            "monto_reembolsado": sales.line_net_cents[idx],
        },
    )


def _inventory(
    rng: np.random.Generator, features: DayFeatures, sales: _Sales, products: _Products
) -> Table:
    n_b, n_p = len(cat.BRANCHES), len(products.popularity)
    months = int(features.month_index.max()) + 1
    completed = sales.line_completed
    flat = (
        sales.line_branch[completed] * n_p + sales.line_product[completed]
    ) * months + features.month_index[sales.line_day[completed]]
    flat_units = np.bincount(flat, weights=sales.line_qty[completed], minlength=n_b * n_p * months)
    units = flat_units.reshape(n_b, n_p, months)

    month_end = np.array(
        [features.days[np.nonzero(features.month_index == m)[0][-1]] for m in range(months)],
        "datetime64[D]",
    )
    opening = np.array([b.fecha_apertura for b in cat.BRANCHES], "datetime64[D]")
    branch_open = opening[:, None] <= month_end[None, :]  # (B, M)
    launch = np.where(products.launch_day == NULL_INT, -1, products.launch_day)
    month_end_day = (month_end - features.days[0]).astype(np.int64)
    product_live = launch[:, None] <= month_end_day[None, :]  # (P, M)
    exists = branch_open[:, None, :] & product_live[None, :, :]

    open_months = np.maximum(exists.sum(axis=2), 1)
    mean_units = units.sum(axis=2) / open_months
    minimum = np.maximum(2, np.ceil(mean_units * 0.6)).astype(np.int64)
    cover = rng.lognormal(np.log(1.1), 0.45, units.shape)
    stock = np.rint(units * cover).astype(np.int64) + rng.integers(0, 4, units.shape)
    never_sold = units.sum(axis=2) == 0
    stock = np.where(never_sold[:, :, None], rng.integers(0, 8, units.shape), stock)
    minimum = np.where(never_sold, 1, minimum)
    stock = np.where(rng.random(units.shape) < 0.015, 0, stock)

    tvs = products.with_tag("tv")
    top_tv = int(tvs[np.argmax(products.popularity[tvs])])
    so_branch = _branch_index(cat.STOCKOUT_BRANCH_CODE)
    so_month = int(features.month_index[_day_index(features, cat.STOCKOUT_WINDOW[1])])
    stock[so_branch, top_tv, so_month] = 0

    b_idx, p_idx, m_idx = np.nonzero(exists)
    return Table(
        "inventario",
        (
            Column("sucursal_id", "int"),
            Column("producto_id", "int"),
            Column("fecha_corte", "date"),
            Column("stock", "int"),
            Column("stock_minimo", "int"),
        ),
        {
            "sucursal_id": b_idx.astype(np.int64) + 1,
            "producto_id": p_idx.astype(np.int64) + 1,
            "fecha_corte": month_end[m_idx],
            "stock": stock[b_idx, p_idx, m_idx],
            "stock_minimo": np.broadcast_to(minimum[:, :, None], units.shape)[b_idx, p_idx, m_idx],
        },
    )


# -------------------------------------------------------------------------------------------------
# Entry point
# -------------------------------------------------------------------------------------------------


def generate(config: GeneratorConfig | None = None) -> Dataset:
    config = config or GeneratorConfig()
    rng = np.random.default_rng(config.seed)
    features = day_features(config.start, config.end)

    products = _products(rng, features)
    traffic = _traffic(rng, features)
    customers = _customers(rng, config, traffic)
    employees = _employees(rng, config)
    ctx = _Context(rng, config, features, traffic, products, customers, employees)
    sales = _simulate_sales(ctx)
    returns = _returns(rng, features, sales, products)
    inventory = _inventory(rng, features, sales, products)

    return Dataset(
        config=config,
        tables=(
            _regions_table(),
            _branches_table(),
            _categories_table(),
            products.table,
            customers.table,
            employees.table,
            sales.ventas,
            sales.detalle,
            returns,
            inventory,
        ),
    )
