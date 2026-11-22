"""Numeric grounding of summaries (ADR-0014): every number in the text must exist in the data.

Numbers are parsed in Spanish and English formats ("299.672,19", "299,672.19", "4.768", "12,5 %",
"$1,2 M", "3 mil"). An ambiguous token like "4.768" yields several candidate readings; it is
grounded if *any* reading matches an allowed value within the precision the text displays.
"""

from __future__ import annotations

import math
import re
import unicodedata
from collections.abc import Iterable, Sequence
from dataclasses import dataclass
from typing import Literal

from nexus.sql.executor import JsonScalar

NUMBER_WORDS = {
    "uno": 1, "una": 1, "dos": 2, "tres": 3, "cuatro": 4, "cinco": 5, "seis": 6, "siete": 7,
    "ocho": 8, "nueve": 9, "diez": 10, "once": 11, "doce": 12, "quince": 15, "veinte": 20,
}  # fmt: skip

_NUMBER = re.compile(
    r"(?<![\w.,])(?P<num>\d{1,3}(?:[.,\u202f\u00a0 ]\d{3})+(?:[.,]\d+)?|\d+(?:[.,]\d+)?)"
    r"(?P<suffix>\s*(?:%|mil(?:lones)?\b|k\b|m\b|millón\b|millon\b|millones\b))?",
    re.IGNORECASE,
)
_SCALES = {"mil": 1e3, "k": 1e3, "m": 1e6, "millon": 1e6, "millón": 1e6, "millones": 1e6}


@dataclass(frozen=True, slots=True)
class NumberToken:
    raw: str
    readings: tuple[tuple[float, float], ...]  # (value, tolerance)


def _readings(digits: str) -> list[tuple[float, int]]:
    """Possible (value, decimals) readings of a digit string with separators."""
    compact = re.sub(r"[\u202f\u00a0 ]", "", digits)
    out: list[tuple[float, int]] = []
    seps = [c for c in compact if c in ".,"]
    if not seps:
        return [(float(compact), 0)]
    last = compact.rfind(seps[-1])
    tail = compact[last + 1 :]
    # Reading A: last separator is the decimal mark (the other one groups thousands).
    if len(set(seps)) == 2 or len(seps) == 1:
        int_part = re.sub(r"[.,]", "", compact[:last])
        out.append((float(f"{int_part}.{tail}"), len(tail)))
    # Reading B: every separator groups thousands (only when groups are 3 digits).
    if len(set(seps)) == 1 and all(len(g) == 3 for g in re.split(r"[.,]", compact)[1:]):
        out.append((float(re.sub(r"[.,]", "", compact)), 0))
    return out or [(float(re.sub(r"[.,]", "", compact)), 0)]


def extract_numbers(text: str) -> list[NumberToken]:
    tokens: list[NumberToken] = []
    for match in _NUMBER.finditer(text):
        suffix = (match.group("suffix") or "").strip().lower()
        scale = _SCALES.get(suffix, 1.0) if suffix and suffix != "%" else 1.0
        readings = []
        for value, decimals in _readings(match.group("num")):
            tolerance = 0.5 * 10 ** (-decimals) * scale
            readings.append((value * scale, tolerance))
        tokens.append(NumberToken(match.group(0).strip(), tuple(readings)))
    return tokens


def _strip_accents(text: str) -> str:
    return "".join(c for c in unicodedata.normalize("NFKD", text) if not unicodedata.combining(c))


def allowed_values(
    rows_by_step: Iterable[Sequence[Sequence[JsonScalar]]],
    *,
    extra: Iterable[float] = (),
    texts: Iterable[str] = (),
) -> set[float]:
    """Numbers the summary may cite: every numeric cell, numbers inside text cells (e.g. "1.5 L"),
    row counts, and numbers present in ``texts`` (question, assumptions, resolved dates)."""
    values: set[float] = set(extra)
    for rows in rows_by_step:
        values.add(float(len(rows)))
        for row in rows:
            for cell in row:
                if isinstance(cell, bool) or cell is None:
                    continue
                if isinstance(cell, int | float):
                    values.add(float(cell))
                else:
                    values.update(r[0] for t in extract_numbers(str(cell)) for r in t.readings)
    for text in texts:
        values.update(r[0] for t in extract_numbers(text) for r in t.readings)
        for word in re.findall(r"[a-záéíóúñ]+", _strip_accents(text.lower())):
            if word in NUMBER_WORDS:
                values.add(float(NUMBER_WORDS[word]))
    return values


def _matches(value: float, tolerance: float, allowed: set[float]) -> bool:
    if value in allowed:
        return True
    return any(math.isclose(value, a, abs_tol=tolerance + 1e-9) for a in allowed)


def ungrounded(text: str, allowed: set[float]) -> list[str]:
    """Tokens in ``text`` whose every reading is absent from ``allowed``."""
    return [
        token.raw
        for token in extract_numbers(text)
        if not any(_matches(value, tol, allowed) for value, tol in token.readings)
    ]


def format_number(value: float, decimals: int, locale: Literal["es", "en"]) -> str:
    """The UI's number format (``Intl`` es-EC / en-US): grouped thousands, fixed decimals."""
    english = f"{value:,.{decimals}f}"
    if locale == "en":
        return english
    return english.translate(str.maketrans(",.", ".,"))


YEAR_COLUMNS = frozenset({"anio", "año", "ano", "year"})


def quantity_values(
    results: Iterable[tuple[Sequence[str], Sequence[Sequence[JsonScalar]]]],
) -> set[float]:
    """Numeric cells that are quantities: every number in (columns, rows) except year columns.

    Years come from the resolved dates or from ``anio`` columns, and "2.026" would be wrong.
    """
    values: set[float] = set()
    for columns, rows in results:
        wanted = [i for i, name in enumerate(columns) if name.strip().lower() not in YEAR_COLUMNS]
        for row in rows:
            for i in wanted:
                cell = row[i] if i < len(row) else None
                if isinstance(cell, int | float) and not isinstance(cell, bool):
                    values.add(float(cell))
    return values


def localize_numbers(
    text: str, quantities: set[float], locale: Literal["es", "en"], *, keep: Iterable[str] = ()
) -> str:
    """Rewrite each number that cites a quantity in the locale's format, with its shown decimals.

    The model mixes "291,168.77" and "291.168,77" in one Spanish answer. Only tokens that match a
    quantity of the results (``quantity_values``) change; the reading that matched decides the
    value. Left as written:
    - numbers inside ``keep`` strings, i.e. text cells such as "Agua mineral 1.5 L";
    - numbers that come from the question, the dates or text cells (years, "1.5 L");
    - tokens whose readings match different quantities (e.g. "1.500" when 1.5 and 1500 occur).
    """
    lowered = text.lower()
    protected: list[tuple[int, int]] = []
    for phrase in {k.strip().lower() for k in keep if k.strip()}:
        start = lowered.find(phrase)
        while start != -1:
            protected.append((start, start + len(phrase)))
            start = lowered.find(phrase, start + 1)
    pieces: list[str] = []
    last = 0
    for match in _NUMBER.finditer(text):
        start, end = match.span("num")
        if any(p_start <= start < p_end for p_start, p_end in protected):
            continue
        suffix = (match.group("suffix") or "").strip().lower()
        scale = _SCALES.get(suffix, 1.0) if suffix and suffix != "%" else 1.0
        matched = [
            (value, decimals)
            for value, decimals in _readings(match.group("num"))
            if _matches(value * scale, 0.5 * 10 ** (-decimals) * scale, quantities)
        ]
        if len({value for value, _ in matched}) != 1:
            continue
        value, decimals = matched[0]
        pieces += [text[last:start], format_number(value, decimals, locale)]
        last = end
    pieces.append(text[last:])
    return "".join(pieces)
