"""Typed agent state, structured LLM outputs and the runtime context injected into nodes."""

from __future__ import annotations

import operator
from dataclasses import dataclass, field
from datetime import date
from enum import StrEnum
from typing import Annotated, Literal, Protocol, TypedDict

from pydantic import BaseModel, Field

from nexus.agent.catalog import SchemaCatalog
from nexus.agent.charts import ChartSpec
from nexus.agent.glossary import Glossary
from nexus.agent.temporal import ResolvedRange, TimeResolution
from nexus.llm import LLMProvider, TokenUsage
from nexus.rag.retriever import SchemaContext
from nexus.sql.executor import JsonScalar, QueryResult
from nexus.sql.validator import ValidatedSQL, ValidationPolicy


class Intent(StrEnum):
    DATA = "data"
    FOLLOW_UP = "follow_up"
    AMBIGUOUS = "ambiguous"
    OUT_OF_SCOPE = "out_of_scope"


class RunStatus(StrEnum):
    ANSWERED = "answered"
    CLARIFICATION = "clarification"
    REFUSED = "refused"
    FAILED = "failed"


# ---- Structured LLM outputs (validated by Pydantic; their JSON schema constrains decoding) ----


class Understanding(BaseModel):
    intent: Literal["data", "follow_up", "ambiguous", "out_of_scope"]
    standalone_question: str = Field(
        description="La pregunta reescrita para entenderse sola, en español"
    )
    clarification_question: str = Field(default="", description="Solo si intent=ambiguous")
    options: list[str] = Field(
        default_factory=list, description="2 a 4 opciones concretas si es ambigua"
    )
    reason: str = Field(default="", description="Una frase breve")


class Explanation(BaseModel):
    headline: str = Field(description="Una frase con la conclusión principal")
    bullets: list[str] = Field(default_factory=list, description="2 a 4 hallazgos breves")
    caveats: list[str] = Field(
        default_factory=list, description="Advertencias relevantes, si las hay"
    )


class Plan(BaseModel):
    steps: list[str] = Field(description="1 a 4 sub-preguntas autocontenidas, en español")


class SqlCandidate(BaseModel):
    sql: str
    dialect: Literal["postgres"] = "postgres"
    tables_used: list[str] = Field(default_factory=list)
    assumptions: list[str] = Field(default_factory=list, description="Máximo 3, breves, en español")
    rationale: str = Field(default="", description="Una sola frase en español")


# ---- Records kept in state and shown in the UI ----


@dataclass(frozen=True, slots=True)
class ErrorInfo:
    kind: Literal["generation", "validation", "execution", "verification"]
    code: str
    message: str
    retryable: bool = True  # False for timeouts/privileges: rewriting the SQL will not help


@dataclass(frozen=True, slots=True)
class SqlAttempt:
    step: int
    attempt: int
    sql: str
    outcome: Literal["ok", "rejected", "failed", "suspicious", "invalid_output"]
    error: ErrorInfo | None = None
    duration_ms: float | None = None


@dataclass(frozen=True, slots=True)
class StepResult:
    index: int
    question: str
    sql: str
    columns: tuple[str, ...]
    rows: list[tuple[JsonScalar, ...]]
    row_count: int
    truncated: bool
    tables: tuple[str, ...]
    rationale: str
    assumptions: tuple[str, ...]
    warnings: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class HistoryTurn:
    """A previous answered question of the same conversation (short-term memory)."""

    question: str
    standalone: str
    ranges: tuple[ResolvedRange, ...] = ()
    answer: str = ""


@dataclass(frozen=True, slots=True)
class ExplanationResult:
    explanation: Explanation
    grounded: bool
    fallback: bool  # True when the deterministic template replaced an ungrounded model text
    attempts: int
    ungrounded: tuple[str, ...] = ()


@dataclass(frozen=True, slots=True)
class Clarification:
    question: str
    options: tuple[str, ...]


class AgentState(TypedDict, total=False):
    run_id: str
    max_repairs: int
    question: str
    history: list[HistoryTurn]  # previous turns of the conversation (short-term memory)
    intent: Intent
    standalone_question: str
    clarification: Clarification | None
    refusal_reason: str
    schema_context: SchemaContext
    steps: list[str]
    time: TimeResolution
    current_step: int
    attempt: int
    candidate: SqlCandidate | None
    validated: ValidatedSQL | None
    pending: StepResult | None  # executed, awaiting verification
    last_error: ErrorInfo | None
    attempts: Annotated[list[SqlAttempt], operator.add]
    results: Annotated[list[StepResult], operator.add]
    assumptions: Annotated[list[str], operator.add]
    usage: Annotated[list[TokenUsage], operator.add]
    charts: list[ChartSpec]
    explanation: ExplanationResult | None
    status: RunStatus
    answer: str


# ---- Runtime context (dependencies), injected by LangGraph, never stored in state ----


class EventSink(Protocol):
    async def emit(self, event: str, data: dict[str, object]) -> None: ...


class AuditSink(Protocol):
    async def record(
        self,
        *,
        question: str,
        sql: str,
        outcome: str,
        row_count: int | None,
        duration_ms: float | None,
        error_code: str | None,
    ) -> None: ...


class SchemaRetriever(Protocol):
    async def retrieve(self, question: str) -> SchemaContext: ...


class MemorySink(Protocol):
    async def remember(self, *, question: str, standalone: str, status: str) -> None: ...


class QueryRunner(Protocol):
    async def execute(self, query: ValidatedSQL) -> QueryResult: ...


class ResultMasker(Protocol):
    def mask(
        self, sql: str, columns: tuple[str, ...], rows: list[tuple[JsonScalar, ...]]
    ) -> tuple[list[tuple[JsonScalar, ...]], tuple[str, ...]]: ...


@dataclass(frozen=True, slots=True)
class NodeModels:
    """Per-node model routing (ADR-0003); None = provider default."""

    understand: str | None = None
    plan: str | None = None
    generate: str | None = None
    repair: str | None = None
    visualize: str | None = None
    explain: str | None = None


@dataclass(frozen=True, slots=True)
class AgentContext:
    llm: LLMProvider
    catalog: SchemaCatalog
    glossary: Glossary
    policy: ValidationPolicy
    executor: QueryRunner
    as_of: date
    events: EventSink
    audit: AuditSink
    masker: ResultMasker
    retriever: SchemaRetriever
    memory: MemorySink
    models: NodeModels = field(default_factory=NodeModels)
    max_repairs: int = 3
    max_explain_retries: int = 2
    chart_tiebreak: bool = True  # let the model break ties between rule-chosen chart types
    locale: Literal["es", "en"] = "es"
