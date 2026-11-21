"""Typed shape of a stored run result (``runs.result``), exported to the frontend via OpenAPI.

Every field has a default so results stored by earlier versions (or cancelled/failed runs, which
only carry status and answer) still validate.
"""

from __future__ import annotations

from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from nexus.agent.charts import ChartSpec
from nexus.sql.executor import JsonScalar


class _Out(BaseModel):
    # Responses always carry every field: make defaulted fields required in the serialization schema
    # so generated TypeScript types are not needlessly optional.
    model_config = ConfigDict(json_schema_serialization_defaults_required=True)


class TimeRangeOut(_Out):
    expression: str
    start: str
    end: str
    grain: str


class ClarificationOut(_Out):
    question: str
    options: list[str] = Field(default_factory=list)


class StepOut(_Out):
    index: int
    question: str
    sql: str
    columns: list[str]
    rows: list[list[JsonScalar]]
    row_count: int
    truncated: bool = False
    tables: list[str] = Field(default_factory=list)
    rationale: str = ""
    assumptions: list[str] = Field(default_factory=list)
    warnings: list[str] = Field(default_factory=list)


class AttemptErrorOut(_Out):
    kind: str
    code: str
    message: str


class AttemptOut(_Out):
    step: int
    attempt: int
    sql: str
    outcome: Literal["ok", "rejected", "failed", "suspicious", "invalid_output"]
    error: AttemptErrorOut | None = None
    duration_ms: float | None = None


class TokensOut(_Out):
    prompt: int = 0
    completion: int = 0
    calls: int = 0


class ExplanationOut(_Out):
    headline: str
    bullets: list[str] = Field(default_factory=list)
    caveats: list[str] = Field(default_factory=list)
    grounded: bool = True
    fallback: bool = False
    attempts: int = 0
    rejected_numbers: list[str] = Field(default_factory=list)


class RankedTableOut(_Out):
    table: str
    score: float


class RetrievalOut(_Out):
    strategy: str
    tables: list[str]
    ranked: list[RankedTableOut] = Field(default_factory=list)
    joins: list[str] = Field(default_factory=list)
    terms: list[str] = Field(default_factory=list)
    examples: list[str] = Field(default_factory=list)
    forced_tables: list[str] = Field(default_factory=list)


class RunResult(_Out):
    status: Literal["answered", "clarification", "refused", "failed", "cancelled"]
    answer: str = ""
    intent: str | None = None
    standalone_question: str | None = None
    steps: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list)
    time_ranges: list[TimeRangeOut] = Field(default_factory=list)
    clarification: ClarificationOut | None = None
    results: list[StepOut] = Field(default_factory=list)
    attempts: list[AttemptOut] = Field(default_factory=list)
    tokens: TokensOut = Field(default_factory=TokensOut)
    charts: list[ChartSpec] = Field(default_factory=list)
    explanation: ExplanationOut | None = None
    retrieval: RetrievalOut | None = None
