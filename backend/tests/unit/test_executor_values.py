import datetime as dt
import uuid
from decimal import Decimal

import pytest

from nexus.sql.executor import QueryExecutionError, to_json_scalar


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        (None, None),
        (True, True),
        (7, 7),
        (1.5, 1.5),
        ("x", "x"),
        (Decimal("299672.19"), 299672.19),
        (dt.date(2026, 7, 1), "2026-07-01"),
        (dt.datetime(2026, 7, 1, 12, 30), "2026-07-01T12:30:00"),
        (dt.time(8, 15), "08:15:00"),
        (dt.timedelta(minutes=2), 120.0),
        (uuid.UUID("12345678-1234-5678-1234-567812345678"), "12345678-1234-5678-1234-567812345678"),
        (b"\x00\xff", "AP8="),
        ([1, 2], "[1, 2]"),
        ({"a": "ñ", "b": [1]}, '{"a": "ñ", "b": [1]}'),  # real JSON, not Python repr
    ],
)
def test_to_json_scalar(value: object, expected: object) -> None:
    assert to_json_scalar(value) == expected


@pytest.mark.parametrize(
    ("sqlstate", "repairable"),
    [
        ("42703", True),  # undefined column
        ("42P01", True),  # undefined table
        ("22012", True),  # division by zero
        ("21000", True),  # cardinality violation
        ("57014", False),  # statement timeout
        ("42501", False),  # insufficient privilege: rewriting will not grant rights
        ("25006", False),  # read-only transaction
        (None, False),
    ],
)
def test_repairable_classification(sqlstate: str | None, repairable: bool) -> None:
    assert QueryExecutionError("m", sqlstate=sqlstate, duration_ms=1).repairable is repairable
