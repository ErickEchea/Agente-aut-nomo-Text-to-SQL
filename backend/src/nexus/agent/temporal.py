"""Deterministic resolution of relative time expressions (ADR-0008). The LLM never does calendar math.

Input: the question text and the connection's ``as_of`` date (the "today" of its data). Output:
concrete half-open ranges ``[start, end)`` plus a human-readable assumption for each, shown to the user.
Spanish first, English supported.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Callable
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Literal

Grain = Literal["day", "week", "month", "quarter", "semester", "year", "custom"]

MONTHS_ES = (
    "enero", "febrero", "marzo", "abril", "mayo", "junio",
    "julio", "agosto", "septiembre", "octubre", "noviembre", "diciembre",
)  # fmt: skip
MONTHS_EN = (
    "january", "february", "march", "april", "may", "june",
    "july", "august", "september", "october", "november", "december",
)  # fmt: skip
MONTH_ABBR_ES = ("ene", "feb", "mar", "abr", "may", "jun", "jul", "ago", "sep", "oct", "nov", "dic")
NUMBER_WORDS = {
    "un": 1, "uno": 1, "una": 1, "dos": 2, "tres": 3, "cuatro": 4, "cinco": 5, "seis": 6,
    "siete": 7, "ocho": 8, "nueve": 9, "diez": 10, "once": 11, "doce": 12, "one": 1, "two": 2,
    "three": 3, "four": 4, "five": 5, "six": 6, "seven": 7, "eight": 8, "nine": 9, "ten": 10,
    "eleven": 11, "twelve": 12,
}  # fmt: skip
ORDINAL_QUARTER = {"primer": 1, "primero": 1, "segundo": 2, "tercer": 3, "tercero": 3, "cuarto": 4,
                   "first": 1, "second": 2, "third": 3, "fourth": 4}  # fmt: skip
VAGUE_TERMS = ("recientemente", "ultimamente", "hace poco", "ultimos tiempos", "recently", "lately")


@dataclass(frozen=True, slots=True)
class ResolvedRange:
    expression: str  # the text that matched, as written by the user
    start: date
    end: date  # exclusive
    grain: Grain

    @property
    def last_day(self) -> date:
        return self.end - timedelta(days=1)

    def describe(self) -> str:
        """Spanish, human-readable: «último trimestre» = 1 jul 2026 – 30 sep 2026."""
        return f"«{self.expression}» = {_fmt(self.start)} – {_fmt(self.last_day)}"

    def sql_hint(self, column: str = "fecha") -> str:
        return f"{column} >= DATE '{self.start.isoformat()}' AND {column} < DATE '{self.end.isoformat()}'"


@dataclass(frozen=True, slots=True)
class TimeResolution:
    as_of: date
    ranges: tuple[ResolvedRange, ...]
    vague_terms: tuple[str, ...] = field(default_factory=tuple)

    @property
    def assumptions(self) -> tuple[str, ...]:
        notes = [r.describe() for r in self.ranges]
        if self.ranges:
            notes.append(f"Fecha de referencia de los datos: {_fmt(self.as_of)}")
        return tuple(notes)


def _fmt(d: date) -> str:
    return f"{d.day} {MONTH_ABBR_ES[d.month - 1]} {d.year}"


def _normalize(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text.lower())
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def _add_months(d: date, months: int) -> date:
    index = d.year * 12 + (d.month - 1) + months
    year, month0 = divmod(index, 12)
    last_day = _month_end(year, month0 + 1).day
    return date(year, month0 + 1, min(d.day, last_day))


def _month_end(year: int, month: int) -> date:
    first_next = date(year + (month == 12), month % 12 + 1, 1)
    return first_next - timedelta(days=1)


def quarter_start(d: date) -> date:
    return date(d.year, 3 * ((d.month - 1) // 3) + 1, 1)


def _quarter(year: int, q: int) -> tuple[date, date]:
    start = date(year, 3 * (q - 1) + 1, 1)
    return start, _add_months(start, 3)


def _number(token: str) -> int | None:
    if token.isdigit():
        return int(token)
    return NUMBER_WORDS.get(token)


# A rule maps a regex match over normalized text to (start, end_exclusive, grain), or None to skip.
RuleFn = Callable[[re.Match[str], date], tuple[date, date, Grain] | None]


def _previous_quarter(_: re.Match[str], as_of: date) -> tuple[date, date, Grain]:
    end = quarter_start(as_of)
    return _add_months(end, -3), end, "quarter"


def _this_quarter(_: re.Match[str], as_of: date) -> tuple[date, date, Grain]:
    return quarter_start(as_of), as_of, "quarter"


def _previous_month(_: re.Match[str], as_of: date) -> tuple[date, date, Grain]:
    end = as_of.replace(day=1)
    return _add_months(end, -1), end, "month"


def _this_month(_: re.Match[str], as_of: date) -> tuple[date, date, Grain]:
    return as_of.replace(day=1), as_of, "month"


def _previous_year(_: re.Match[str], as_of: date) -> tuple[date, date, Grain]:
    return date(as_of.year - 1, 1, 1), date(as_of.year, 1, 1), "year"


def _this_year(_: re.Match[str], as_of: date) -> tuple[date, date, Grain]:
    return date(as_of.year, 1, 1), as_of, "year"


def _previous_week(_: re.Match[str], as_of: date) -> tuple[date, date, Grain]:
    this_monday = as_of - timedelta(days=as_of.weekday())
    return this_monday - timedelta(days=7), this_monday, "week"


def _this_week(_: re.Match[str], as_of: date) -> tuple[date, date, Grain]:
    return as_of - timedelta(days=as_of.weekday()), as_of, "week"


def _today(_: re.Match[str], as_of: date) -> tuple[date, date, Grain]:
    return as_of, as_of + timedelta(days=1), "day"


def _yesterday(_: re.Match[str], as_of: date) -> tuple[date, date, Grain]:
    return as_of - timedelta(days=1), as_of, "day"


def _last_n(m: re.Match[str], as_of: date) -> tuple[date, date, Grain] | None:
    n = _number(m.group("n"))
    if n is None or n <= 0:
        return None
    unit = m.group("unit")
    if unit.startswith(("dia", "day")):
        return as_of - timedelta(days=n), as_of, "day"
    if unit.startswith(("semana", "week")):
        return as_of - timedelta(weeks=n), as_of, "week"
    if unit.startswith(("mes", "month")):
        return _add_months(as_of, -n), as_of, "month"
    return _add_months(as_of, -12 * n), as_of, "year"


def _named_quarter(m: re.Match[str], as_of: date) -> tuple[date, date, Grain]:
    groups = m.groupdict()
    q = int(groups["q"]) if groups.get("q") else ORDINAL_QUARTER[groups["ord"]]
    if groups.get("year"):
        start, end = _quarter(int(groups["year"]), q)
    else:
        # Most recent quarter with that number that has already started.
        start, end = _quarter(as_of.year, q)
        if start >= as_of:
            start, end = _quarter(as_of.year - 1, q)
    return start, min(end, max(as_of, start + timedelta(days=1))), "quarter"


def _semester(m: re.Match[str], as_of: date) -> tuple[date, date, Grain]:
    half = 1 if m.group("ord") in {"primer", "primero", "first"} else 2
    year = int(m.group("year")) if m.group("year") else as_of.year
    start = date(year, 1 if half == 1 else 7, 1)
    if not m.group("year") and start >= as_of:
        start = start.replace(year=year - 1)
    end = _add_months(start, 6)
    return start, min(end, max(as_of, start + timedelta(days=1))), "semester"


def _named_month(m: re.Match[str], as_of: date) -> tuple[date, date, Grain]:
    name = m.group("month")
    month = (MONTHS_ES.index(name) if name in MONTHS_ES else MONTHS_EN.index(name)) + 1
    if m.group("year"):
        year = int(m.group("year"))
    else:
        year = as_of.year if date(as_of.year, month, 1) < as_of else as_of.year - 1
    start = date(year, month, 1)
    end = _add_months(start, 1)
    return start, min(end, max(as_of, start + timedelta(days=1))), "month"


def _named_year(m: re.Match[str], as_of: date) -> tuple[date, date, Grain]:
    year = int(m.group("year"))
    start, end = date(year, 1, 1), date(year + 1, 1, 1)
    return start, min(end, max(as_of, start + timedelta(days=1))), "year"


# English "may" is also a verb: it only counts as a month when a year follows (separate rule).
_MONTH_ALT = "|".join(m for m in MONTHS_ES + MONTHS_EN if m != "may")
_YEAR = r"(?P<year>20\d{2})"
_OF = r"(?:\s+(?:de(?:l)?|of)\s+|\s+)"

RULES: tuple[tuple[re.Pattern[str], RuleFn], ...] = (
    (re.compile(rf"\b(?:q|t)(?P<q>[1-4]){_OF}?{_YEAR}?\b"), _named_quarter),
    (re.compile(rf"\b(?P<ord>primer|primero|segundo|tercer|tercero|cuarto|first|second|third|fourth)\s+(?:trimestre|quarter)(?:{_OF}(?:ano\s+)?{_YEAR})?\b"), _named_quarter),
    (re.compile(rf"\b(?P<ord>primer|primero|segundo|first|second)\s+(?:semestre|half)(?:{_OF}(?:ano\s+)?{_YEAR})?\b"), _semester),
    (re.compile(r"\b(?:(?:ultimo|pasado|anterior)\s+trimestre|trimestre\s+(?:pasado|anterior)|(?:last|previous)\s+quarter)\b"), _previous_quarter),
    (re.compile(r"\b(?:(?:este|actual)\s+trimestre|trimestre\s+(?:actual|en\s+curso)|this\s+quarter|qtd)\b"), _this_quarter),
    (re.compile(r"\b(?:ultim[oa]s|past|last)\s+(?P<n>\d+|[a-z]+)\s+(?P<unit>dias?|semanas?|mes(?:es)?|anos?|days?|weeks?|months?|years?)\b"), _last_n),
    (re.compile(r"\b(?:(?:ultimo|pasado|anterior)\s+mes|mes\s+(?:pasado|anterior)|(?:last|previous)\s+month)\b"), _previous_month),
    (re.compile(r"\b(?:(?:este|actual)\s+mes|mes\s+(?:actual|en\s+curso)|this\s+month|mtd)\b"), _this_month),
    (re.compile(r"\b(?:ano\s+(?:pasado|anterior)|(?:last|previous)\s+year)\b"), _previous_year),
    (re.compile(r"\b(?:(?:este|actual)\s+ano|ano\s+(?:actual|en\s+curso)|en\s+lo\s+que\s+va\s+del\s+ano|this\s+year|ytd)\b"), _this_year),
    (re.compile(r"\b(?:semana\s+(?:pasada|anterior)|ultima\s+semana|(?:last|previous)\s+week)\b"), _previous_week),
    (re.compile(r"\b(?:esta\s+semana|semana\s+(?:actual|en\s+curso)|this\s+week)\b"), _this_week),
    (re.compile(r"\b(?:hoy|today)\b"), _today),
    (re.compile(r"\b(?:ayer|yesterday)\b"), _yesterday),
    (re.compile(rf"\b(?P<month>{_MONTH_ALT})(?:{_OF}{_YEAR})?\b"), _named_month),
    (re.compile(rf"\b(?P<month>may){_OF}{_YEAR}\b"), _named_month),
    (re.compile(rf"\b(?:en|durante|del|de|el|ano|in|during)\s+{_YEAR}\b"), _named_year),
)  # fmt: skip

_SAME_PERIOD_LAST_YEAR = re.compile(
    r"\b(?:mismo\s+periodo\s+del\s+ano\s+(?:pasado|anterior)|same\s+period\s+last\s+year)\b"
)


def resolve(question: str, as_of: date) -> TimeResolution:
    """Find every time expression in ``question`` and resolve it against ``as_of``."""
    text = _normalize(question)
    taken: list[tuple[int, int]] = []
    found: list[tuple[int, ResolvedRange]] = []

    def overlaps(a: int, b: int) -> bool:
        return any(a < y and x < b for x, y in taken)

    # Reserve "same period last year" first so its "año anterior" is not read as a range.
    same = _SAME_PERIOD_LAST_YEAR.search(text)
    if same:
        taken.append((same.start(), same.end()))

    for pattern, rule in RULES:
        for match in pattern.finditer(text):
            if overlaps(match.start(), match.end()):
                continue
            outcome = rule(match, as_of)
            if outcome is None:
                continue
            start, end, grain = outcome
            expression = question[match.start() : match.end()]
            taken.append((match.start(), match.end()))
            found.append((match.start(), ResolvedRange(expression, start, end, grain)))

    found.sort(key=lambda item: item[0])
    ranges = [r for _, r in found]
    if same and ranges:
        base = ranges[0]
        ranges.append(
            ResolvedRange(
                question[same.start() : same.end()],
                base.start.replace(year=base.start.year - 1),
                base.end.replace(year=base.end.year - 1),
                base.grain,
            )
        )
    vague = tuple(term for term in VAGUE_TERMS if term in text)
    return TimeResolution(as_of=as_of, ranges=tuple(ranges), vague_terms=vague)
