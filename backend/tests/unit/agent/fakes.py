"""Test doubles for the agent (tests only — never imported by production code)."""

from __future__ import annotations

import hashlib
import math
import unicodedata
from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import date

from pydantic import BaseModel

from nexus.agent.catalog import ColumnInfo, ForeignKey, SchemaCatalog, TableInfo
from nexus.agent.glossary import Glossary, GlossaryTerm
from nexus.agent.state import AgentContext, Explanation
from nexus.llm import Completion, GenerationOptions, Message, StructuredOutputError, TokenUsage
from nexus.rag.joins import connect
from nexus.rag.retriever import RankedTable, SchemaContext
from nexus.security.pii import PiiMasker
from nexus.sql.executor import QueryExecutionError, QueryResult
from nexus.sql.validator import ValidatedSQL, ValidationPolicy

USAGE = TokenUsage(model="fake", prompt_tokens=100, completion_tokens=20, duration_ms=1.0)


class ScriptedLLM:
    """Returns queued outputs per schema; an Exception in the queue is raised instead."""

    def __init__(
        self,
        script: dict[type[BaseModel], list[BaseModel | Exception]],
        defaults: dict[type[BaseModel], BaseModel] | None = None,
    ) -> None:
        self.script = {k: list(v) for k, v in script.items()}
        # Used when a schema's queue is empty (e.g. the explanation of every test run).
        self.defaults: dict[type[BaseModel], BaseModel] = (
            {Explanation: Explanation(headline="Resumen de resultados.")}
            if defaults is None
            else defaults
        )
        self.calls: list[tuple[str, list[Message]]] = []

    @property
    def default_model(self) -> str:
        return "fake"

    async def complete[T: BaseModel](
        self, messages: Sequence[Message], schema: type[T], options: GenerationOptions | None = None
    ) -> Completion[T]:
        self.calls.append((schema.__name__, list(messages)))
        queue = self.script.get(schema)
        if not queue:
            if schema in self.defaults:
                default = self.defaults[schema]
                return Completion(parsed=default, raw=default.model_dump_json(), usage=USAGE)  # type: ignore[arg-type]
            raise AssertionError(f"unexpected LLM call for {schema.__name__}")
        item = queue.pop(0)
        if isinstance(item, Exception):
            raise item
        assert isinstance(item, schema)
        return Completion(parsed=item, raw=item.model_dump_json(), usage=USAGE)

    async def embed(self, texts: Sequence[str], model: str | None = None) -> list[list[float]]:
        return [hash_embedding(t) for t in texts]


def hash_embedding(text: str, dims: int = 64) -> list[float]:
    """Deterministic bag-of-words vector (tests only): shared words → higher cosine similarity."""
    vector = [0.0] * dims
    for word in unicodedata.normalize("NFKD", text.lower()).split():
        clean = "".join(c for c in word if c.isalnum())
        if len(clean) > 2:
            vector[int(hashlib.md5(clean.encode()).hexdigest(), 16) % dims] += 1.0  # noqa: S324
    norm = math.sqrt(sum(v * v for v in vector)) or 1.0
    return [v / norm for v in vector]


def invalid_output() -> StructuredOutputError:
    return StructuredOutputError("response does not match SqlCandidate", "{oops", USAGE)


Responder = Callable[[str], QueryResult]


class FakeExecutor:
    """Maps SQL → result via the first matching substring rule; QueryExecutionError raises."""

    def __init__(self, rules: list[tuple[str, QueryResult | QueryExecutionError]]) -> None:
        self.rules = rules
        self.executed: list[str] = []

    async def execute(self, query: ValidatedSQL) -> QueryResult:
        self.executed.append(query.sql)
        for needle, outcome in self.rules:
            if needle in query.sql:
                if isinstance(outcome, QueryExecutionError):
                    raise outcome
                return outcome
        raise AssertionError(f"no fake result for: {query.sql}")


def result(columns: tuple[str, ...], rows: list[tuple[object, ...]]) -> QueryResult:
    return QueryResult(columns, rows, len(rows), False, 5.0)  # type: ignore[arg-type]


def db_error(sqlstate: str, message: str) -> QueryExecutionError:
    return QueryExecutionError(message, sqlstate=sqlstate, duration_ms=3.0)


@dataclass
class RecordingSink:
    events: list[tuple[str, dict[str, object]]] = field(default_factory=list)

    async def emit(self, event: str, data: dict[str, object]) -> None:
        self.events.append((event, data))

    def nodes(self, event: str = "node.completed") -> list[str]:
        return [str(d["node"]) for e, d in self.events if e == event]


@dataclass
class RecordingMemory:
    remembered: list[dict[str, str]] = field(default_factory=list)

    async def remember(self, *, question: str, standalone: str, status: str) -> None:
        self.remembered.append({"question": question, "standalone": standalone, "status": status})


class FullSchemaRetriever:
    """Returns every table (what Phase 2 sent); records the questions it was asked."""

    def __init__(self, cat: SchemaCatalog) -> None:
        self._catalog = cat
        self.questions: list[str] = []

    async def retrieve(self, question: str) -> SchemaContext:
        self.questions.append(question)
        tables, joins = connect(self._catalog, sorted(self._catalog.tables))
        return SchemaContext(
            tables=tuple(tables),
            joins=tuple(joins),
            ranked=tuple(RankedTable(t, 1.0) for t in tables),
            terms=(),
            strategy="full-schema (test)",
        )


@dataclass
class RecordingAudit:
    entries: list[dict[str, object]] = field(default_factory=list)

    async def record(self, **entry: object) -> None:
        self.entries.append(entry)


TABLES = ("regiones", "sucursales", "categorias", "productos", "clientes", "empleados",
          "ventas", "detalle_ventas", "inventario", "devoluciones")  # fmt: skip


def catalog() -> SchemaCatalog:
    def table(name: str, cols: list[str], fks: list[ForeignKey] | None = None) -> TableInfo:
        return TableInfo(
            name=name,
            comment=f"Tabla {name}",
            columns=tuple(ColumnInfo(c, "integer", False, f"columna {c}") for c in cols),
            primary_key=(cols[0],),
            foreign_keys=tuple(fks or []),
        )

    tables = {name: table(name, [f"{name}_id", "nombre"]) for name in TABLES}
    tables["ventas"] = table(
        "ventas", ["venta_id", "sucursal_id", "fecha_venta", "estado"],
        [ForeignKey("sucursal_id", "sucursales", "sucursal_id")],
    )  # fmt: skip
    return SchemaCatalog(schema="retail", tables=tables)


def context(llm: ScriptedLLM, executor: FakeExecutor, **overrides: object) -> AgentContext:
    values: dict[str, object] = {
        "llm": llm,
        "catalog": catalog(),
        "glossary": Glossary(
            "USD", (GlossaryTerm("ingresos", ("ventas netas",), "Suma neta sin IVA."),), ()
        ),
        "policy": ValidationPolicy(allowed_tables=frozenset(TABLES), max_rows=1000),
        "executor": executor,
        "as_of": date(2026, 11, 1),
        "events": RecordingSink(),
        "audit": RecordingAudit(),
        "masker": PiiMasker([]),
        "memory": RecordingMemory(),
        "chart_tiebreak": False,
    }
    values.update(overrides)
    values.setdefault("retriever", FullSchemaRetriever(values["catalog"]))  # type: ignore[arg-type]
    return AgentContext(**values)  # type: ignore[arg-type]
