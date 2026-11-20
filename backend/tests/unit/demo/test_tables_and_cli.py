import json
from datetime import date, datetime

import numpy as np
import pytest

from nexus.demo.cli import main
from nexus.demo.tables import NULL_INT, Column, Table


def test_iter_rows_converts_types_for_copy() -> None:
    table = Table(
        "t",
        (
            Column("id", "int"),
            Column("parent", "int", nullable=True),
            Column("amount", "money"),
            Column("day", "date", nullable=True),
            Column("at", "timestamp"),
            Column("flag", "bool"),
            Column("name", "text"),
        ),
        {
            "id": np.array([1, 2]),
            "parent": np.array([NULL_INT, 1]),
            "amount": np.array([123456, -5]),
            "day": np.array(["2025-01-02", "NaT"], "datetime64[D]"),
            "at": np.array(["2025-01-02T03:04:05", "2025-12-31T23:59:59"], "datetime64[s]"),
            "flag": np.array([True, False]),
            "name": np.array(["Ñandú", "x"]),
        },
    )
    rows = list(table.iter_rows())
    assert rows[0] == (
        1,
        None,
        "1234.56",
        date(2025, 1, 2),
        datetime(2025, 1, 2, 3, 4, 5),
        True,
        "Ñandú",
    )
    assert rows[1] == (2, 1, "-0.05", None, datetime(2025, 12, 31, 23, 59, 59), False, "x")
    assert len(table) == 2


def test_table_rejects_object_and_ragged_columns() -> None:
    with pytest.raises(TypeError, match="object arrays"):
        Table("t", (Column("a", "text"),), {"a": np.array(["x", None], dtype=object)})
    with pytest.raises(ValueError, match="ragged"):
        Table(
            "t",
            (Column("a", "int"), Column("b", "int")),
            {"a": np.array([1]), "b": np.array([1, 2])},
        )
    with pytest.raises(ValueError, match="do not match"):
        Table("t", (Column("a", "int"),), {"b": np.array([1])})


def test_cli_dry_run_prints_counts_and_checksum(capsys: pytest.CaptureFixture[str]) -> None:
    assert main(["--dry-run", "--scale", "0.02"]) == 0
    out = capsys.readouterr().out.strip().splitlines()[-1]
    payload = json.loads(out)
    assert len(payload["checksum"]) == 64
    assert payload["row_counts"]["sucursales"] == 24
    assert 5_000 < payload["row_counts"]["detalle_ventas"] < 15_000
