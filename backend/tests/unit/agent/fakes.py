"""Test doubles for the agent (tests only — never imported by production code)."""

from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass, field
from datetime import date

from pydantic import BaseModel

from nexus.agent.catalog import ColumnInfo, ForeignKey, SchemaCatalog, TableInfo
from nexus.agent.glossary import Glossary, GlossaryTerm
from nexus.agent.state import AgentContext
from nexus.llm import Completion, GenerationOptions, Message, StructuredOutputError, TokenUsage
from nexus.security.pii import PiiMasker
from nexus.sql.executor import QueryExecutionError, QueryResult
from nexus.sql.validator import ValidatedSQL, ValidationPolicy

USAGE = TokenUsage(model="fake", prompt_tokens=100, completion_tokens=20, duration_ms=1.0)


class ScriptedLLM:
    """Returns queued outputs per schema; an Exception in the queue is raised instead."""

    def __init__(self, script: dict[type[BaseModel], list[BaseModel | Exception]]) -> None:
        self.script = {k: list(v) for k, v in script.items()}
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
            raise AssertionError(f"unexpected LLM call for {schema.__name__}")
        item = queue.pop(0)
        if isinstance(item, Exception):
            raise item
        assert isinstance(item, schema)
        return Completion(parsed=item, raw=item.model_dump_json(), usage=USAGE)

    async def embed(self, texts: Sequence[str], model: str | None = None) -> list[list[float]]:
        return [[0.0] for _ in texts]


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
    }
    values.update(overrides)
    return AgentContext(**values)  # type: ignore[arg-type]
