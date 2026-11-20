from datetime import date

import numpy as np
import pytest
from hypothesis import given
from hypothesis import strategies as st

from nexus.demo.calendar import (
    COSTA,
    SIERRA,
    black_friday,
    carnaval,
    day_features,
    easter_sunday,
    nth_weekday,
    school_season,
    ticket_volume,
)


@pytest.mark.parametrize(
    ("year", "expected"),
    [
        (2024, date(2024, 3, 31)),
        (2025, date(2025, 4, 20)),
        (2026, date(2026, 4, 5)),
        (2038, date(2038, 4, 25)),
    ],
)
def test_easter_sunday(year: int, expected: date) -> None:
    assert easter_sunday(year) == expected


@given(st.integers(min_value=1900, max_value=2200))
def test_easter_is_always_a_sunday_between_march_22_and_april_25(year: int) -> None:
    easter = easter_sunday(year)
    assert easter.weekday() == 6
    assert date(year, 3, 22) <= easter <= date(year, 4, 25)


def test_carnaval_dates() -> None:
    assert carnaval(2025) == (date(2025, 3, 3), date(2025, 3, 4))
    assert carnaval(2026) == (date(2026, 2, 16), date(2026, 2, 17))


def test_black_friday_and_mothers_day() -> None:
    assert black_friday(2024) == date(2024, 11, 29)
    assert black_friday(2025) == date(2025, 11, 28)
    assert nth_weekday(2025, 5, 6, 2) == date(2025, 5, 11)
    assert nth_weekday(2026, 5, 6, 2) == date(2026, 5, 10)


def test_day_features_basics() -> None:
    f = day_features(date(2024, 11, 1), date(2026, 10, 31))
    assert f.n == 730
    assert f.weekday[0] == date(2024, 11, 1).weekday()
    assert f.month_index[-1] == 23
    assert f.is_month_end.sum() == 24
    assert f.day_of_month[f.is_month_end].min() >= 28


def test_traffic_peaks_on_black_friday_and_before_christmas() -> None:
    f = day_features(date(2024, 11, 1), date(2026, 10, 31))
    volume = ticket_volume(f)
    idx = {str(d): i for i, d in enumerate(f.days.astype("datetime64[D]"))}
    bf = volume[idx["2025-11-28"], SIERRA]
    regular_friday = volume[idx["2025-10-17"], SIERRA]
    assert bf > 2 * regular_friday
    assert volume[idx["2025-12-23"], SIERRA] > 1.8 * volume[idx["2025-10-23"], SIERRA]
    assert volume[idx["2025-12-25"], SIERRA] < volume[idx["2025-12-24"], SIERRA] / 3


def test_carnaval_moves_traffic_from_sierra_to_costa() -> None:
    f = day_features(date(2024, 11, 1), date(2026, 10, 31))
    volume = ticket_volume(f)
    i = int(np.nonzero(f.days == np.datetime64("2026-02-16"))[0][0])
    assert volume[i, COSTA] > volume[i, SIERRA]


def test_school_seasons_follow_each_regime() -> None:
    f = day_features(date(2024, 11, 1), date(2026, 10, 31))
    school = school_season(f)
    april = (f.month == 4) & (f.year == 2025)
    august = (f.month == 8) & (f.year == 2025)
    assert school[april, COSTA].mean() > 0.4 > school[april, SIERRA].mean()
    assert school[august, SIERRA].mean() > 0.3 > school[august, COSTA].mean()
