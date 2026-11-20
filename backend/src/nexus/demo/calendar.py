"""Ecuadorian commercial calendar: the demand multipliers behind the demo data's seasonality.

All functions are pure and vectorized over a ``datetime64[D]`` day array. Two school regimes
exist in Ecuador and drive regional effects: ``SIERRA`` (Sierra-Amazonía) and ``COSTA``
(Costa-Galápagos).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Final

import numpy as np
from numpy.typing import NDArray

SIERRA: Final = 0
COSTA: Final = 1
N_REGIMES: Final = 2

FloatArray = NDArray[np.float64]
DayArray = NDArray[np.datetime64]


def easter_sunday(year: int) -> date:
    """Gregorian Easter (anonymous algorithm / Meeus-Jones-Butcher)."""
    a = year % 19
    b, c = divmod(year, 100)
    d, e = divmod(b, 4)
    f = (b + 8) // 25
    g = (b - f + 1) // 3
    h = (19 * a + b - d - g + 15) % 30
    i, k = divmod(c, 4)
    el = (32 + 2 * e + 2 * i - h - k) % 7
    m = (a + 11 * h + 22 * el) // 451
    month, day = divmod(h + el - 7 * m + 114, 31)
    return date(year, month, day + 1)


def nth_weekday(year: int, month: int, weekday: int, n: int) -> date:
    """n-th ``weekday`` (Mon=0) of a month, n >= 1."""
    first = date(year, month, 1)
    offset = (weekday - first.weekday()) % 7
    return first + timedelta(days=offset + 7 * (n - 1))


def black_friday(year: int) -> date:
    """Friday after the fourth Thursday of November (adopted by Ecuadorian retail)."""
    return nth_weekday(year, 11, 3, 4) + timedelta(days=1)


def carnaval(year: int) -> tuple[date, date]:
    """Carnaval Monday and Tuesday (48 and 47 days before Easter)."""
    easter = easter_sunday(year)
    return easter - timedelta(days=48), easter - timedelta(days=47)


def national_holidays(year: int) -> list[date]:
    """National holidays with reduced store traffic (Carnaval handled separately)."""
    good_friday = easter_sunday(year) - timedelta(days=2)
    return [
        date(year, 1, 1),
        good_friday,
        date(year, 5, 1),
        date(year, 5, 24),
        date(year, 8, 10),
        date(year, 10, 9),
        date(year, 11, 2),
        date(year, 11, 3),
        date(year, 12, 25),
    ]


WORLD_CUP_2026: Final = (date(2026, 6, 11), date(2026, 7, 19))


@dataclass(frozen=True, slots=True)
class DayFeatures:
    days: DayArray
    weekday: NDArray[np.int64]  # Mon=0
    day_of_month: NDArray[np.int64]
    month: NDArray[np.int64]  # 1..12
    year: NDArray[np.int64]
    month_index: NDArray[np.int64]  # 0.. months since the first day's month
    is_month_end: NDArray[np.bool_]
    years_elapsed: FloatArray

    @property
    def n(self) -> int:
        return int(self.days.shape[0])


def day_features(start: date, end: date) -> DayFeatures:
    one_day = np.timedelta64(1, "D")
    days = np.arange(np.datetime64(start, "D"), np.datetime64(end, "D") + one_day)
    months = days.astype("datetime64[M]")
    years = days.astype("datetime64[Y]").astype(np.int64) + 1970
    month_num = (months.astype(np.int64) % 12) + 1
    dom = (days - months.astype("datetime64[D]")).astype(np.int64) + 1
    next_day_month = (days + one_day).astype("datetime64[M]")
    weekday = (days.astype(np.int64) + 3) % 7  # 1970-01-01 was a Thursday
    month_index = months.astype(np.int64) - months[0].astype(np.int64)
    elapsed = (days - days[0]).astype(np.float64) / 365.25
    return DayFeatures(
        days=days,
        weekday=weekday,
        day_of_month=dom,
        month=month_num,
        year=years,
        month_index=month_index,
        is_month_end=next_day_month != months,
        years_elapsed=elapsed,
    )


def _mask(days: DayArray, first: date, last: date) -> NDArray[np.bool_]:
    """Inclusive date window."""
    return (days >= np.datetime64(first, "D")) & (days <= np.datetime64(last, "D"))


def _bump(days: DayArray, start: date, peak: date, end: date) -> FloatArray:
    """Triangular bump in [0, 1]: 0 at start, 1 at peak, 0 at end."""
    t = days.astype(np.int64).astype(np.float64)
    s, p, e = (float(np.datetime64(x, "D").astype(np.int64)) for x in (start, peak, end))
    rise = np.clip((t - s) / max(p - s, 1.0), 0.0, 1.0)
    fall = np.clip((e - t) / max(e - p, 1.0), 0.0, 1.0)
    return np.where(t <= p, rise, fall) * ((t >= s) & (t <= e))


def years_in(features: DayFeatures) -> range:
    return range(int(features.year.min()), int(features.year.max()) + 1)


def school_season(features: DayFeatures) -> FloatArray:
    """Back-to-school intensity (0..1) per day and regime, shape (D, 2).

    Costa-Galápagos classes start late April / early May; Sierra-Amazonía in early September.
    """
    out = np.zeros((features.n, N_REGIMES))
    for year in years_in(features):
        out[:, COSTA] += _bump(
            features.days, date(year, 3, 20), date(year, 4, 25), date(year, 5, 12)
        )
        out[:, SIERRA] += _bump(
            features.days, date(year, 8, 5), date(year, 8, 30), date(year, 9, 15)
        )
    return np.clip(out, 0.0, 1.0)


def ticket_volume(features: DayFeatures) -> FloatArray:
    """Store-traffic multiplier per day and regime, shape (D, 2); no branch-specific events."""
    d = features.days
    wd_factor = np.array([0.86, 0.83, 0.88, 0.95, 1.12, 1.30, 1.06])[features.weekday]
    base = wd_factor.copy()

    # Quincena paydays (15th and month end) and the day after.
    payday = np.isin(features.day_of_month, (15, 16)) | features.is_month_end
    payday |= features.day_of_month == 1
    base *= np.where(payday, 1.15, 1.0)

    # Post-holiday slump in January.
    base *= np.where(features.month == 1, 0.86, 1.0)

    out = np.repeat(base[:, None], N_REGIMES, axis=1)
    for year in years_in(features):
        # Christmas ramp, décimo tercer sueldo (paid by Dec 24) and holiday closures.
        xmas_ramp = _bump(d, date(year, 11, 30), date(year, 12, 23), date(year, 12, 24))
        out *= (1.0 + 0.85 * xmas_ramp)[:, None]
        out *= np.where(_mask(d, date(year, 12, 15), date(year, 12, 24)), 1.20, 1.0)[:, None]
        out *= np.where(d == np.datetime64(date(year, 12, 25)), 0.35, 1.0)[:, None]
        out *= np.where(d == np.datetime64(date(year, 12, 31)), 0.80, 1.0)[:, None]

        # Décimo cuarto sueldo: March in Costa-Galápagos, August in Sierra-Amazonía.
        out[:, COSTA] *= np.where(_mask(d, date(year, 3, 10), date(year, 3, 20)), 1.15, 1.0)
        out[:, SIERRA] *= np.where(_mask(d, date(year, 8, 10), date(year, 8, 20)), 1.15, 1.0)

        # Black Friday weekend + Cyber Monday.
        bf = black_friday(year)
        for offset, factor in ((0, 2.2), (1, 1.6), (2, 1.3), (3, 1.25)):
            out *= np.where(d == np.datetime64(bf + timedelta(days=offset)), factor, 1.0)[:, None]

        # Día de la Madre (2nd Sunday of May): the week before, peak on Saturday.
        mother = nth_weekday(year, 5, 6, 2)
        out *= np.where(
            _mask(d, mother - timedelta(days=7), mother - timedelta(days=2)), 1.12, 1.0
        )[:, None]
        out *= np.where(d == np.datetime64(mother - timedelta(days=1)), 1.40, 1.0)[:, None]

        # Día del Padre (3rd Sunday of June).
        father = nth_weekday(year, 6, 6, 3)
        out *= np.where(d == np.datetime64(father - timedelta(days=1)), 1.20, 1.0)[:, None]

        # Carnaval: the Sierra travels to the coast.
        for day in carnaval(year):
            hit = d == np.datetime64(day)
            out[:, SIERRA] *= np.where(hit, 0.70, 1.0)
            out[:, COSTA] *= np.where(hit, 1.20, 1.0)

        for holiday in national_holidays(year):
            out *= np.where(d == np.datetime64(holiday), 0.75, 1.0)[:, None]

    # Mild back-to-school traffic on top of the category-mix shift.
    out *= 1.0 + 0.06 * school_season(features)
    return out


def category_multipliers(features: DayFeatures, category_names: list[str]) -> FloatArray:
    """Category-mix multiplier per day, regime and category, shape (D, 2, C)."""
    d = features.days
    n_cat = len(category_names)
    out = np.ones((features.n, N_REGIMES, n_cat))
    idx = {name: i for i, name in enumerate(category_names)}
    school = school_season(features)

    def scale(category: str, factor: FloatArray, regime: int | None = None) -> None:
        if regime is None:
            out[:, :, idx[category]] *= factor[:, None]
        else:
            out[:, regime, idx[category]] *= factor

    for year in years_in(features):
        xmas = _bump(d, date(year, 11, 25), date(year, 12, 22), date(year, 12, 26))
        scale("Juguetes", 1.0 + 3.8 * xmas)
        scale("Electrónica", 1.0 + 0.9 * xmas)
        scale("Ropa y Calzado", 1.0 + 0.8 * xmas)
        scale("Hogar", 1.0 + 0.35 * xmas)
        scale("Cuidado Personal", 1.0 + 0.25 * xmas)
        scale(
            "Alimentos y Bebidas",
            np.where(_mask(d, date(year, 12, 20), date(year, 12, 31)), 1.3, 1.0),
        )

        bf = black_friday(year)
        bf_window = _mask(d, bf, bf + timedelta(days=3))
        scale("Electrónica", np.where(bf_window, 3.0, 1.0))
        scale("Electrodomésticos", np.where(bf_window, 2.2, 1.0))

        mother = nth_weekday(year, 5, 6, 2)
        mother_week = _mask(d, mother - timedelta(days=8), mother - timedelta(days=1))
        scale("Electrodomésticos", np.where(mother_week, 2.2, 1.0))
        scale("Cuidado Personal", np.where(mother_week, 1.5, 1.0))
        scale("Hogar", np.where(mother_week, 1.3, 1.0))

        father = nth_weekday(year, 6, 6, 3)
        father_week = _mask(d, father - timedelta(days=8), father - timedelta(days=1))
        for category, factor in (
            ("Ferretería", 1.8),
            ("Deportes", 1.6),
            ("Ropa y Calzado", 1.4),
            ("Electrónica", 1.3),
        ):
            scale(category, np.where(father_week, factor, 1.0))

        # Día del Niño (June 1) and Carnaval water games.
        scale("Juguetes", np.where(_mask(d, date(year, 5, 25), date(year, 6, 1)), 1.8, 1.0))
        carnival_monday, _ = carnaval(year)
        carnival_window = _mask(
            d, carnival_monday - timedelta(days=6), carnival_monday + timedelta(days=1)
        )
        scale("Juguetes", np.where(carnival_window, 2.0, 1.0))

        # New-year fitness resolutions.
        scale("Deportes", np.where(_mask(d, date(year, 1, 2), date(year, 1, 31)), 1.5, 1.0))

    world_cup = _mask(d, WORLD_CUP_2026[0] - timedelta(days=14), WORLD_CUP_2026[1])
    scale("Deportes", np.where(world_cup, 1.8, 1.0))
    scale("Electrónica", np.where(world_cup, 1.25, 1.0))

    # School supplies follow each regime's calendar; uniforms ride along.
    for regime in (SIERRA, COSTA):
        scale("Útiles Escolares", 0.55 + 5.5 * school[:, regime], regime)
        scale("Ropa y Calzado", 1.0 + 0.4 * school[:, regime], regime)
    return out


def online_share(features: DayFeatures) -> FloatArray:
    """Online share of tickets: ~5 % growing to ~12 % over the period, with a Cyber Monday spike."""
    total = max(float(features.years_elapsed[-1]), 1e-9)
    share = 0.05 + 0.07 * (features.years_elapsed / total)
    for year in years_in(features):
        cyber_monday = black_friday(year) + timedelta(days=3)
        share = np.where(features.days == np.datetime64(cyber_monday), share * 2.5, share)
    return np.asarray(share, dtype=np.float64)
