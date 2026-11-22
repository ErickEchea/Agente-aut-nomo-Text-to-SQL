"""Execution accuracy: does a predicted result match a frozen gold result? (ADR-0015, ADR-0022)

Cells become canonical tokens: numbers rounded half-up to 2 decimals (``n:12.35``), dates and
midnight timestamps as ISO dates (``d:2025-07-01``), other timestamps (``t:…``), booleans
(``b:true``), NULL (``∅``) and trimmed text (``s:…``). Rows are compared as multisets unless the
question asks for a ranking. Column names and order are ignored: each gold column is matched to a
predicted column with the same values, and extra predicted columns are tolerated.

One equivalence is allowed on purpose: a gold column named ``mes``/``anio`` (a ``date_trunc``
period) matches the same period written as ``2026-03``, ``2026-03-01``, a month number or Spanish
month name (when the gold spans a single year), or a year number. Percent versus fraction, or a
coarser rounding, is not equivalent: the question says what it wants.
"""

from __future__ import annotations

import itertools
import re
from collections import Counter
from collections.abc import Callable, Sequence
from dataclasses import dataclass
from decimal import ROUND_HALF_UP, Decimal
from typing import Literal

from nexus.bench.golden import FrozenResult

NULL = "∅"
MAX_MAPPINGS = 5000
_CENT = Decimal("0.01")
_DATE = re.compile(
    r"^(\d{4}-\d{2}-\d{2})(?:[T ](\d{2}:\d{2}:\d{2})(?:\.\d+)?(?:[+-]\d{2}:?\d{2}|Z)?)?$"
)
_NUMBER = re.compile(r"^-?\d+(?:\.\d+)?$")
_YEAR_MONTH = re.compile(r"^(\d{4})-(\d{2})")
MONTHS_ES = (
    "enero", "febrero", "marzo", "abril", "mayo", "junio",
    "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre",
)  # fmt: skip
MONTH_COLUMNS = frozenset({"mes", "month"})
YEAR_COLUMNS = frozenset({"anio", "año", "ano", "year"})

Kind = Literal["value", "month", "year"]
Reason = Literal["ok", "no_result", "row_count", "missing_column", "row_values", "order"]


def _number(value: Decimal) -> str:
    rounded = value.quantize(_CENT, rounding=ROUND_HALF_UP)
    return f"n:{rounded + 0}"  # + 0 turns -0.00 into 0.00


def normalize(value: object) -> str:
    """Canonical token for one cell (JSON scalars from the executor, or Decimal/str)."""
    if value is None:
        return NULL
    if isinstance(value, bool):
        return f"b:{str(value).lower()}"
    if isinstance(value, int | float | Decimal):
        number = Decimal(str(value))
        return _number(number) if number.is_finite() else f"s:{value}"
    text = str(value).strip()
    date_match = _DATE.match(text)
    if date_match:
        day, time = date_match.groups()
        return f"d:{day}" if time in (None, "00:00:00") else f"t:{day}T{time}"
    if _NUMBER.match(text):
        return _number(Decimal(text))
    return f"s:{text}"


def column_kind(name: str) -> Kind:
    lowered = name.strip().lower()
    if lowered in MONTH_COLUMNS:
        return "month"
    if lowered in YEAR_COLUMNS:
        return "year"
    return "value"


def _gold_key(kind: Kind, token: str) -> str:
    if kind == "month" and token.startswith(("d:", "t:")):
        return token[2:9]
    if kind == "year" and token.startswith(("d:", "t:")):
        return token[2:6]
    return token


def _month_key(token: str, single_year: str | None) -> str | None:
    if token.startswith(("d:", "t:")):
        return token[2:9]
    payload = token[2:]
    if token.startswith("s:"):
        match = _YEAR_MONTH.match(payload)
        if match:
            return f"{match.group(1)}-{match.group(2)}"
        lowered = payload.lower()
        if single_year and lowered in MONTHS_ES:
            return f"{single_year}-{MONTHS_ES.index(lowered) + 1:02d}"
    if token.startswith("n:") and single_year:
        number = Decimal(payload)
        if number == number.to_integral_value() and 1 <= number <= 12:
            return f"{single_year}-{int(number):02d}"
    return None


def _year_key(token: str) -> str | None:
    if token.startswith(("d:", "t:")):
        return token[2:6]
    payload = token[2:]
    if token.startswith("n:"):
        number = Decimal(payload)
        if number == number.to_integral_value() and 1900 <= number <= 2100:
            return str(int(number))
    if token.startswith("s:") and re.fullmatch(r"\d{4}", payload):
        return payload
    return None


def _predicted_key(kind: Kind, single_year: str | None) -> Callable[[str], str | None]:
    if kind == "month":
        return lambda token: _month_key(token, single_year)
    if kind == "year":
        return _year_key
    return lambda token: token


@dataclass(frozen=True, slots=True)
class Match:
    ok: bool
    reason: Reason
    mapping: tuple[int, ...] = ()  # predicted column index for each gold column


def compare(
    gold: FrozenResult,
    columns: Sequence[str],
    rows: Sequence[Sequence[object]],
    *,
    order_matters: bool,
) -> Match:
    """Does one predicted result (columns + raw rows) answer one gold result?"""
    if not columns:
        return Match(False, "no_result")
    if len(rows) != len(gold.rows):
        return Match(False, "row_count")
    predicted = [[normalize(cell) for cell in row] for row in rows]
    width = len(columns)
    kinds = [column_kind(name) for name in gold.columns]
    gold_cols = [
        [_gold_key(kinds[j], row[j]) for row in gold.rows] for j in range(len(gold.columns))
    ]
    keys: list[Callable[[str], str | None]] = []
    for j, kind in enumerate(kinds):
        years = {key[:4] for key in gold_cols[j]} if kind == "month" else set()
        keys.append(_predicted_key(kind, next(iter(years)) if len(years) == 1 else None))

    candidates: list[list[int]] = []
    for j, gold_col in enumerate(gold_cols):
        wanted = Counter(gold_col)
        found = [k for k in range(width) if Counter(keys[j](row[k]) for row in predicted) == wanted]
        if not found:
            return Match(False, "missing_column")
        candidates.append(found)

    gold_rows = [tuple(col[i] for col in gold_cols) for i in range(len(gold.rows))]
    gold_bag = Counter(gold_rows)
    reason: Reason = "row_values"
    for mapping in itertools.islice(itertools.product(*candidates), MAX_MAPPINGS):
        if len(set(mapping)) != len(mapping):
            continue  # two gold columns cannot read the same predicted column
        projected = [tuple(keys[j](row[k]) for j, k in enumerate(mapping)) for row in predicted]
        if Counter(projected) != gold_bag:
            continue
        if not order_matters or projected == gold_rows:
            return Match(True, "ok", mapping)
        reason = "order"
    return Match(False, reason)


@dataclass(frozen=True, slots=True)
class PredictedResult:
    columns: tuple[str, ...]
    rows: list[tuple[object, ...]]


def score_answer(
    gold: Sequence[FrozenResult], predicted: Sequence[PredictedResult], *, order_matters: bool
) -> Match:
    """Every gold part must be answered by a distinct predicted step result."""
    if not predicted:
        return Match(False, "no_result")
    used: set[int] = set()
    worst: Reason = "ok"
    for part in gold:
        best: Match | None = None
        for index, result in enumerate(predicted):
            if index in used:
                continue
            outcome = compare(part, result.columns, result.rows, order_matters=order_matters)
            if outcome.ok:
                used.add(index)
                best = outcome
                break
            best = (
                best
                if best is not None and _rank(best.reason) >= _rank(outcome.reason)
                else outcome
            )
        if best is None or not best.ok:
            return Match(False, best.reason if best is not None else "no_result")
    return Match(True, worst)


def _rank(reason: Reason) -> int:
    """How close a failed comparison came (used to report the most informative reason)."""
    return ("no_result", "row_count", "missing_column", "row_values", "order", "ok").index(reason)
