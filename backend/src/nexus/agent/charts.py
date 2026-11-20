"""Chart selection (rules first, the model only breaks genuine ties) and validated ECharts specs.

The spec is a typed subset of the ECharts option (Pydantic); the frontend applies the design-token
theme. Data never round-trips through the model: the model may only pick one of the candidates the
rules produced.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Sequence
from typing import Literal

from pydantic import BaseModel, Field

from nexus.sql.executor import JsonScalar

ChartKind = Literal["bar", "line", "pie", "scatter", "kpi", "table"]
MAX_CATEGORIES = 30
MAX_PIE_SLICES = 6
SHARE_WORDS = (
    "participacion",
    "porcentaje",
    "proporcion",
    "distribucion",
    "composicion",
    "share",
    "%",
)


class AxisSpec(BaseModel):
    type: Literal["category", "value", "time"]
    name: str | None = None
    data: list[str] | None = None


class SeriesSpec(BaseModel):
    type: Literal["bar", "line", "pie", "scatter"]
    name: str
    data: list[float | None] | list[list[float | str | None]] | list[dict[str, float | str]]
    stack: str | None = None


class EChartsOption(BaseModel):
    title: dict[str, str]
    tooltip: dict[str, str] = Field(default_factory=lambda: {"trigger": "axis"})
    legend: dict[str, bool] | None = None
    xAxis: AxisSpec | None = None  # noqa: N815 — ECharts option name
    yAxis: AxisSpec | None = None  # noqa: N815
    series: list[SeriesSpec]


class Kpi(BaseModel):
    label: str
    value: float


class ChartSpec(BaseModel):
    kind: ChartKind
    step: int
    candidates: list[ChartKind]
    reason: str
    option: EChartsOption | None = None
    kpis: list[Kpi] = Field(default_factory=list)


class ChartChoice(BaseModel):
    """Structured output when the model breaks a tie between rule candidates."""

    kind: Literal["bar", "line", "pie", "scatter"]


ColumnRole = Literal["numeric", "temporal", "category"]
_ISO_DATE = re.compile(r"^\d{4}-\d{2}(-\d{2})?([T ]\d{2}:\d{2}(:\d{2})?)?")


def column_role(values: Sequence[JsonScalar]) -> ColumnRole:
    present = [v for v in values if v is not None]
    if present and all(isinstance(v, int | float) and not isinstance(v, bool) for v in present):
        return "numeric"
    if present and all(isinstance(v, str) and _ISO_DATE.match(v) for v in present):
        return "temporal"
    return "category"


def _norm(text: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFKD", text.lower()) if not unicodedata.combining(c)
    )


def candidates_for(
    question: str, columns: Sequence[str], rows: Sequence[Sequence[JsonScalar]]
) -> tuple[list[ChartKind], str, dict[str, int]]:
    """Rule-based candidates (first = preferred), a reason, and the column indexes to plot."""
    if not rows:
        return ["table"], "sin filas", {}
    roles = [column_role([r[i] for r in rows]) for i in range(len(columns))]
    numeric = [i for i, r in enumerate(roles) if r == "numeric"]
    temporal = [i for i, r in enumerate(roles) if r == "temporal"]
    category = [i for i, r in enumerate(roles) if r == "category"]
    wants_share = any(w in _norm(question) for w in SHARE_WORDS)

    if len(rows) == 1 and numeric and len(numeric) <= 4:
        return ["kpi"], "una sola fila con métricas", {"values": numeric[0]}
    if temporal and numeric:
        kinds: list[ChartKind] = ["line", "bar"] if len(rows) > 3 else ["bar", "line"]
        return kinds, "serie temporal", {"x": temporal[0], "y": numeric[0]}
    if category and numeric and len(rows) <= MAX_CATEGORIES:
        non_negative = all((r[numeric[0]] or 0) >= 0 for r in rows)  # type: ignore[operator]
        if wants_share and non_negative and len(rows) <= MAX_PIE_SLICES:
            return (
                ["pie", "bar"],
                "participación de categorías",
                {"x": category[0], "y": numeric[0]},
            )
        if non_negative and len(rows) <= MAX_PIE_SLICES and len(numeric) == 1:
            return ["bar", "pie"], "pocas categorías", {"x": category[0], "y": numeric[0]}
        return ["bar"], "comparación de categorías", {"x": category[0], "y": numeric[0]}
    if len(numeric) >= 2 and not category:
        return ["scatter"], "relación entre dos métricas", {"x": numeric[0], "y": numeric[1]}
    return ["table"], "forma no apta para gráfico", {}


def _num(value: JsonScalar) -> float:
    if isinstance(value, bool) or not isinstance(value, int | float):
        raise TypeError(f"not numeric: {value!r}")
    return float(value)


def build_spec(
    kind: ChartKind,
    step: int,
    *,
    candidates: list[ChartKind],
    reason: str,
    title: str,
    columns: Sequence[str],
    rows: Sequence[Sequence[JsonScalar]],
    picks: dict[str, int],
) -> ChartSpec:
    if kind == "table":
        return ChartSpec(kind="table", step=step, candidates=candidates, reason=reason)
    if kind == "kpi":
        row = rows[0]
        kpis = [
            Kpi(label=columns[i], value=float(row[i]))  # type: ignore[arg-type]
            for i in range(len(columns))
            if column_role([row[i]]) == "numeric"
        ]
        return ChartSpec(kind="kpi", step=step, candidates=candidates, reason=reason, kpis=kpis)

    x, y = picks["x"], picks["y"]
    labels = [str(r[x]) for r in rows]
    values = [None if r[y] is None else float(r[y]) for r in rows]  # type: ignore[arg-type]
    title_opt = {"text": title[:120]}
    if kind == "pie":
        option = EChartsOption(
            title=title_opt,
            tooltip={"trigger": "item"},
            legend={"show": True},
            series=[
                SeriesSpec(
                    type="pie",
                    name=columns[y],
                    data=[
                        {"name": n, "value": v or 0.0} for n, v in zip(labels, values, strict=True)
                    ],
                )
            ],
        )
    elif kind == "scatter":
        option = EChartsOption(
            title=title_opt,
            tooltip={"trigger": "item"},
            xAxis=AxisSpec(type="value", name=columns[x]),
            yAxis=AxisSpec(type="value", name=columns[y]),
            series=[
                SeriesSpec(
                    type="scatter",
                    name=columns[y],
                    data=[
                        [_num(r[x]), _num(r[y])]
                        for r in rows
                        if r[x] is not None and r[y] is not None
                    ],
                )
            ],
        )
    else:
        option = EChartsOption(
            title=title_opt,
            xAxis=AxisSpec(type="category", name=columns[x], data=labels),
            yAxis=AxisSpec(type="value", name=columns[y]),
            series=[SeriesSpec(type=kind, name=columns[y], data=values)],
        )
    return ChartSpec(kind=kind, step=step, candidates=candidates, reason=reason, option=option)
