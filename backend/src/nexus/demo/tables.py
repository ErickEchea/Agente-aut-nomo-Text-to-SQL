"""Columnar in-memory tables produced by the generator and consumed by the loader."""

from __future__ import annotations

import hashlib
from collections.abc import Iterator
from dataclasses import dataclass
from datetime import date, datetime
from typing import Literal

import numpy as np
from numpy.typing import NDArray

ColumnKind = Literal["int", "text", "date", "timestamp", "money", "bool"]

NULL_INT = -1


@dataclass(frozen=True, slots=True)
class Column:
    name: str
    kind: ColumnKind
    nullable: bool = False


@dataclass(frozen=True, slots=True)
class Table:
    """A table as named numpy columns.

    Conventions: money is ``int64`` cents; nullable ints use ``NULL_INT``; nullable dates use
    ``NaT``; text is a numpy unicode array (never ``object``, so the checksum is byte-stable).
    """

    name: str
    columns: tuple[Column, ...]
    data: dict[str, NDArray[np.generic]]

    def __post_init__(self) -> None:
        names = [c.name for c in self.columns]
        if set(names) != set(self.data):
            raise ValueError(
                f"{self.name}: columns {names} do not match data keys {list(self.data)}"
            )
        lengths = {len(array) for array in self.data.values()}
        if len(lengths) > 1:
            raise ValueError(f"{self.name}: ragged columns {lengths}")
        for column in self.columns:
            if self.data[column.name].dtype == np.dtype(object):
                raise TypeError(f"{self.name}.{column.name}: object arrays are not allowed")

    def __len__(self) -> int:
        return len(next(iter(self.data.values()))) if self.data else 0

    @property
    def column_names(self) -> tuple[str, ...]:
        return tuple(c.name for c in self.columns)

    def update_hash(self, digest: hashlib._Hash) -> None:
        digest.update(self.name.encode())
        for column in self.columns:
            array = np.ascontiguousarray(self.data[column.name])
            digest.update(f"{column.name}:{array.dtype.str}:{len(array)}".encode())
            digest.update(array.tobytes())

    def iter_rows(self) -> Iterator[tuple[object, ...]]:
        """Rows as Python values ready for ``COPY`` (money as exact decimal strings)."""
        converted = [_to_python(column, self.data[column.name]) for column in self.columns]
        return zip(*converted, strict=True)


def _money(cents: int) -> str:
    sign = "-" if cents < 0 else ""
    whole, frac = divmod(abs(cents), 100)
    return f"{sign}{whole}.{frac:02d}"


def _to_python(column: Column, array: NDArray[np.generic]) -> list[object]:
    match column.kind:
        case "money":
            return [_money(int(v)) for v in array.tolist()]
        case "int":
            values = array.tolist()
            if column.nullable:
                return [None if v == NULL_INT else v for v in values]
            return list(values)
        case "date":
            dates: list[date | None] = array.astype("datetime64[D]").tolist()
            return list(dates)
        case "timestamp":
            stamps: list[datetime | None] = array.astype("datetime64[s]").tolist()
            return list(stamps)
        case "bool":
            return [bool(v) for v in array.tolist()]
        case "text":
            return [str(v) for v in array.tolist()]
