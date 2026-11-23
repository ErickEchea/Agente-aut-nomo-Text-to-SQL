"""Agent nodes. Each is a small async function ``(state, ctx) -> NodeResult``.

``NodeResult.update`` goes into the graph state; ``NodeResult.summary`` is what the live
timeline shows (JSON-safe, already trimmed). Nodes never emit events themselves:
:mod:`nexus.agent.graph` wraps them.
"""

from __future__ import annotations

import re
from collections.abc import Sequence
from dataclasses import dataclass, field, replace
from typing import Literal

from nexus.agent import prompts
from nexus.agent.charts import ChartChoice, ChartSpec, build_spec, candidates_for
from nexus.agent.grounding import (
    allowed_values,
    localize_numbers,
    quantity_values,
    ungrounded,
)
from nexus.agent.state import (
    AgentContext,
    AgentState,
    Clarification,
    ErrorInfo,
    Explanation,
    ExplanationResult,
    Intent,
    Plan,
    RunStatus,
    SqlAttempt,
    SqlCandidate,
    StepResult,
    Understanding,
)
from nexus.agent.temporal import resolve
from nexus.llm import Completion, GenerationOptions, StructuredOutputError
from nexus.security.guard import check_question
from nexus.sql.columns import catalog_hint
from nexus.sql.executor import QueryExecutionError
from nexus.sql.validator import SQLValidationError, validate_sql

MAX_STEPS = 4
# A plan step must be a natural-language sub-question. Small models sometimes answer the planner
# with SQL (often in another dialect); such a plan is discarded instead of reaching generate_sql.
_SQL_STEP = re.compile(
    r"^\s*(select|with|insert|update|delete)\b|\bfrom\s+\w+.*\b(join|where|group\s+by)\b|;\s*$",
    re.IGNORECASE | re.DOTALL,
)
PREVIEW_ROWS = 5
# Sampling for the one retry when a repair returned the very SQL it was asked to fix.
REPEAT_TEMPERATURE = 0.7
TIMEOUT_SQLSTATES = {"57014", "55P03", "MY3024", "MY1969", "SQLITE_INTERRUPT"}


class StateInvariantError(RuntimeError):
    """A node ran without the state its routing guarantees (a graph wiring bug)."""


def _require[T](value: T | None, name: str) -> T:
    if value is None:
        raise StateInvariantError(f"state[{name!r}] is missing")
    return value


@dataclass(frozen=True, slots=True)
class NodeResult:
    update: dict[str, object]
    summary: dict[str, object] = field(default_factory=dict)


def _sql_context(state: AgentState, ctx: AgentContext) -> str:
    """Only the retrieved sub-schema, its join path, the relevant glossary terms, sample values
    and verified examples (ADR-0007). Without a retrieval result, the whole schema is used."""
    context = state.get("schema_context")
    if context is None:
        return prompts.sql_context(
            ctx.catalog.render(), ctx.glossary.render(), state.get("time"), profile=ctx.dialect
        )
    return prompts.sql_context(
        ctx.catalog.render(context.tables),
        ctx.glossary.render(context.terms) if context.terms else ctx.glossary.render(),
        state.get("time"),
        joins=[j.condition() for j in context.joins],
        samples=context.samples,
        examples=[(e.question, e.sql) for e in context.examples],
        profile=ctx.dialect,
    )


def _step_question(state: AgentState) -> str:
    return state["steps"][state["current_step"]]


def _attempt_record(
    state: AgentState,
    sql: str,
    outcome: str,
    error: ErrorInfo | None,
    duration_ms: float | None = None,
) -> SqlAttempt:
    return SqlAttempt(
        step=state["current_step"],
        attempt=state.get("attempt", 1),
        sql=sql,
        outcome=outcome,  # type: ignore[arg-type]
        error=error,
        duration_ms=duration_ms,
    )


# ------------------------------------------------------------------------------------------------
# understand · plan · resolve_time
# ------------------------------------------------------------------------------------------------


async def understand(state: AgentState, ctx: AgentContext) -> NodeResult:
    question = state["question"]
    verdict = check_question(question)
    if not verdict.allowed:
        return NodeResult(
            {"intent": Intent.OUT_OF_SCOPE, "refusal_reason": verdict.reason},
            {"intent": Intent.OUT_OF_SCOPE.value, "guard": str(verdict.category)},
        )

    completion = await ctx.llm.complete(
        prompts.understand_messages(question, state.get("history", [])),
        Understanding,
        GenerationOptions(model=ctx.models.understand, max_tokens=300),
    )
    u = completion.parsed
    intent = Intent(u.intent)
    update: dict[str, object] = {
        "intent": intent,
        "standalone_question": u.standalone_question.strip() or question,
        "usage": [completion.usage],
    }
    if intent is Intent.AMBIGUOUS:
        update["clarification"] = Clarification(
            u.clarification_question or "¿Puedes precisar la pregunta?", tuple(u.options[:4])
        )
    if intent is Intent.OUT_OF_SCOPE:
        update["refusal_reason"] = (
            "La pregunta no trata sobre los datos disponibles (ventas, productos, sucursales, "
            "clientes, empleados, inventario y devoluciones)."
        )
    return NodeResult(
        update,
        {
            "intent": intent.value,
            "standalone_question": update["standalone_question"],
            "reason": u.reason,
        },
    )


async def plan(state: AgentState, ctx: AgentContext) -> NodeResult:
    question = state["standalone_question"]
    try:
        completion = await ctx.llm.complete(
            prompts.plan_messages(question),
            Plan,
            GenerationOptions(model=ctx.models.plan, max_tokens=300),
        )
    except StructuredOutputError as exc:
        # Splitting is an optimization: an unusable plan (e.g. truncated JSON) means one step.
        summary_invalid: dict[str, object] = {
            "steps": [question],
            "strategy": "single_query",
            "rejected": "invalid_plan",
        }
        return NodeResult(
            {"steps": [question], "current_step": 0, "usage": [exc.usage]}, summary_invalid
        )
    steps = [s.strip() for s in completion.parsed.steps if s.strip()][:MAX_STEPS] or [question]
    summary: dict[str, object] = {}
    if any(_SQL_STEP.search(step) for step in steps):
        steps = [question]
        summary["rejected"] = "sql_in_plan"
    summary |= {"steps": steps, "strategy": "multi_query" if len(steps) > 1 else "single_query"}
    return NodeResult({"steps": steps, "current_step": 0, "usage": [completion.usage]}, summary)


async def resolve_time(state: AgentState, ctx: AgentContext) -> NodeResult:
    history = state.get("history", [])
    previous = history[-1].ranges if history else ()
    resolution = resolve(state["standalone_question"], ctx.as_of, previous=previous)
    update: dict[str, object] = {"time": resolution, "assumptions": list(resolution.assumptions)}
    if resolution.vague_terms and not resolution.ranges:
        update["intent"] = Intent.AMBIGUOUS
        update["clarification"] = Clarification(
            f"¿A qué periodo te refieres con «{resolution.vague_terms[0]}»?",
            ("el último mes", "el último trimestre", "en lo que va del año", "todo el historial"),
        )
    return NodeResult(
        update,
        {
            "ranges": [r.describe() for r in resolution.ranges],
            "as_of": resolution.as_of.isoformat(),
            "vague_terms": list(resolution.vague_terms),
        },
    )


# ------------------------------------------------------------------------------------------------
# generate_sql · repair
# ------------------------------------------------------------------------------------------------


def _candidate_result(
    state: AgentState,
    candidate: SqlCandidate | None,
    attempt: int,
    usage: object,
    error: ErrorInfo | None,
) -> NodeResult:
    update: dict[str, object] = {
        "candidate": candidate,
        "validated": None,
        "attempt": attempt,
        "last_error": error,
        "usage": [usage],
    }
    if candidate is None and error is not None:
        update["attempts"] = [
            SqlAttempt(state["current_step"], attempt, "", "invalid_output", error)
        ]
    summary: dict[str, object] = {"step": state["current_step"], "attempt": attempt}
    if candidate is not None:
        summary |= {
            "sql": candidate.sql,
            "rationale": candidate.rationale,
            "assumptions": candidate.assumptions[:3],
        }
    if error is not None:
        summary["error"] = {"code": error.code, "message": error.message}
    return NodeResult(update, summary)


async def generate_sql(state: AgentState, ctx: AgentContext) -> NodeResult:
    try:
        completion = await ctx.llm.complete(
            prompts.generate_messages(
                _sql_context(state, ctx),
                _step_question(state),
                state["standalone_question"],
                prompts.sql_rules(ctx.dialect, ctx.catalog.schema),
            ),
            SqlCandidate,
            GenerationOptions(model=ctx.models.generate, max_tokens=900),
        )
    except StructuredOutputError as exc:
        error = ErrorInfo("generation", "invalid_output", str(exc))
        return _candidate_result(state, None, 1, exc.usage, error)
    return _candidate_result(state, completion.parsed, 1, completion.usage, None)


def _same_sql(a: str, b: str) -> bool:
    """Equal up to whitespace, letter case and a trailing semicolon."""

    def canonical(sql: str) -> str:
        return " ".join(sql.strip().rstrip(";").split()).lower()

    return canonical(a) == canonical(b)


def _already_tried(state: AgentState, ctx: AgentContext, sql: str, previous: str) -> bool:
    """Is ``sql`` the SQL being repaired, or one this step already tried? Attempts store the
    validator's rendering (or the raw SQL when it was rejected), so both forms are compared. The
    7B model was seen alternating between two failing queries, not only repeating the last one."""
    if previous and _same_sql(sql, previous):
        return True
    try:
        rendered = validate_sql(sql, ctx.policy).sql
    except SQLValidationError:
        rendered = sql
    step = state["current_step"]
    return any(
        a.step == step and (_same_sql(a.sql, rendered) or _same_sql(a.sql, sql))
        for a in state.get("attempts", [])
    )


async def repair(state: AgentState, ctx: AgentContext) -> NodeResult:
    error = _require(state.get("last_error"), "last_error")
    previous = state["candidate"].sql if state.get("candidate") else ""  # type: ignore[union-attr]
    attempt = state.get("attempt", 1) + 1

    async def ask(repeated: bool) -> Completion[SqlCandidate]:
        # Greedy decoding is deterministic: once a repair returns the SQL it was given, the same
        # prompt would return it again. The retry says so and samples (seeded: still reproducible).
        return await ctx.llm.complete(
            prompts.repair_messages(
                _sql_context(state, ctx),
                _step_question(state),
                previous,
                error,
                prompts.sql_rules(ctx.dialect, ctx.catalog.schema),
                repeated=repeated,
            ),
            SqlCandidate,
            GenerationOptions(
                model=ctx.models.repair,
                max_tokens=900,
                seed=7 + attempt,
                temperature=REPEAT_TEMPERATURE if repeated else 0.0,
            ),
        )

    try:
        completion = await ask(repeated=False)
    except StructuredOutputError as exc:
        new_error = ErrorInfo("generation", "invalid_output", str(exc))
        result = _candidate_result(state, None, attempt, exc.usage, new_error)
        # Keep the last good candidate's SQL in state for the next repair prompt.
        result.update["candidate"] = state.get("candidate")
        return result
    usage = [completion.usage]
    repeated = _already_tried(state, ctx, completion.parsed.sql, previous)
    if repeated:
        try:
            retry = await ask(repeated=True)
        except StructuredOutputError as exc:
            usage.append(exc.usage)  # keep the first answer: it is at least valid output
        else:
            usage.append(retry.usage)
            completion = retry
    result = _candidate_result(state, completion.parsed, attempt, usage[0], None)
    result.update["usage"] = usage
    result.summary["previous_sql"] = previous
    result.summary["fixing"] = {"kind": error.kind, "code": error.code}
    if repeated:
        result.summary["retried_repeat"] = True
    return result


# ------------------------------------------------------------------------------------------------
# validate · execute · verify_results
# ------------------------------------------------------------------------------------------------


async def validate(state: AgentState, ctx: AgentContext) -> NodeResult:
    candidate = _require(state.get("candidate"), "candidate")
    try:
        validated = validate_sql(candidate.sql, ctx.policy)
    except SQLValidationError as exc:
        error = ErrorInfo("validation", exc.code.value, exc.detail)
        await ctx.audit.record(
            question=_step_question(state),
            sql=candidate.sql,
            outcome="rejected",
            row_count=None,
            duration_ms=None,
            error_code=exc.code.value,
        )
        return NodeResult(
            {
                "validated": None,
                "last_error": error,
                "attempts": [_attempt_record(state, candidate.sql, "rejected", error)],
            },
            {"ok": False, "code": exc.code.value, "detail": exc.detail},
        )
    return NodeResult(
        {"validated": validated, "last_error": None},
        {
            "ok": True,
            "sql": validated.sql,
            "tables": list(validated.tables),
            "limit": validated.limit_applied,
            "limit_added": validated.limit_was_added,
        },
    )


async def execute(state: AgentState, ctx: AgentContext) -> NodeResult:
    validated = _require(state.get("validated"), "validated")
    candidate = _require(state.get("candidate"), "candidate")
    try:
        result = await ctx.executor.execute(validated)
    except QueryExecutionError as exc:
        code = exc.sqlstate or "unknown"
        # The engine names the column it rejected but not where it looked: the catalog says both.
        hint = catalog_hint(validated.sql, ctx.dialect.sqlglot, ctx.catalog, exc.message)
        message = f"{exc.message}\n{hint}" if hint else exc.message
        error = ErrorInfo("execution", code, message, retryable=exc.repairable)
        await ctx.audit.record(
            question=_step_question(state),
            sql=validated.sql,
            outcome="error",
            row_count=None,
            duration_ms=exc.duration_ms,
            error_code=code,
        )
        return NodeResult(
            {
                "last_error": error,
                "attempts": [
                    _attempt_record(state, validated.sql, "failed", error, exc.duration_ms)
                ],
            },
            {
                "ok": False,
                "sqlstate": code,
                "message": exc.message,
                "duration_ms": round(exc.duration_ms, 1),
            }
            | ({"hint": hint} if hint else {}),
        )

    rows, masked = ctx.masker.mask(validated.sql, result.columns, result.rows)
    await ctx.audit.record(
        question=_step_question(state),
        sql=validated.sql,
        outcome="ok",
        row_count=result.row_count,
        duration_ms=result.duration_ms,
        error_code=None,
    )
    warnings = []
    if result.truncated:
        warnings.append(f"Resultado truncado a {result.row_count} filas.")
    if masked:
        warnings.append(f"Columnas con datos personales enmascarados: {', '.join(masked)}.")
    pending = StepResult(
        index=state["current_step"],
        question=_step_question(state),
        sql=validated.sql,
        columns=result.columns,
        rows=rows,
        row_count=result.row_count,
        truncated=result.truncated,
        tables=validated.tables,
        rationale=candidate.rationale,
        assumptions=tuple(candidate.assumptions[:3]),
        warnings=tuple(warnings),
    )
    return NodeResult(
        {"pending": pending, "last_error": None},
        {
            "ok": True,
            "row_count": result.row_count,
            "truncated": result.truncated,
            "duration_ms": result.duration_ms,
            "columns": list(result.columns),
            "preview": [list(r) for r in rows[:PREVIEW_ROWS]],
            "masked_columns": list(masked),
        },
    )


def _verification_issue(
    state: AgentState, pending: StepResult, ctx: AgentContext
) -> ErrorInfo | None:
    glossary_problems = ctx.glossary.violations(pending.question, pending.sql)
    if glossary_problems:
        return ErrorInfo(
            "verification",
            "glossary_violation",
            "La consulta no cumple la definición del glosario: " + " ".join(glossary_problems),
        )
    time = state.get("time")
    if time is not None and time.ranges:
        missing = [r for r in time.ranges if r.start.isoformat() not in pending.sql]
        if len(missing) == len(time.ranges):
            hint = "; ".join(
                f"{r.describe()} → >= '{r.start}' AND < '{r.end}'" for r in time.ranges
            )
            return ErrorInfo(
                "verification",
                "date_filter_missing",
                f"La consulta no aplica el rango de fechas resuelto. Usa exactamente: {hint}.",
            )
    if pending.row_count == 0:
        detail = "La consulta no devolvió filas."
        if time is not None and time.ranges:
            detail += (
                " Revisa que los filtros de fecha y de texto coincidan con los datos y el "
                "rango resuelto."
            )
        return ErrorInfo("verification", "empty_result", detail)
    for i, column in enumerate(pending.columns):
        if all(row[i] is None for row in pending.rows):
            return ErrorInfo(
                "verification",
                "null_column",
                f"La columna «{column}» es NULL en todas las filas; probablemente un JOIN o "
                "filtro es incorrecto.",
            )
    return None


async def verify_results(state: AgentState, ctx: AgentContext) -> NodeResult:
    pending = _require(state.get("pending"), "pending")
    issue = _verification_issue(state, pending, ctx)
    can_retry = state.get("attempt", 1) <= state.get("max_repairs", ctx.max_repairs)
    if issue is not None and can_retry:
        return NodeResult(
            {
                "last_error": issue,
                "attempts": [_attempt_record(state, pending.sql, "suspicious", issue)],
            },
            {"ok": False, "code": issue.code, "message": issue.message},
        )
    accepted = pending
    if issue is not None:  # budget exhausted: accept, but say so
        accepted = replace(pending, warnings=(*pending.warnings, issue.message))
    return NodeResult(
        {
            "results": [accepted],
            "attempts": [_attempt_record(state, pending.sql, "ok", None)],
            "pending": None,
            "candidate": None,
            "validated": None,
            "last_error": None,
            "attempt": 0,
            "current_step": state["current_step"] + 1,
        },
        {"ok": True, "warnings": list(accepted.warnings), "step": state["current_step"]},
    )


# ------------------------------------------------------------------------------------------------
# respond
# ------------------------------------------------------------------------------------------------


def _format_value(value: object) -> str:
    if isinstance(value, float):
        # Ecuadorian convention: 299.672,19
        return f"{value:,.2f}".translate(str.maketrans(",.", ".,"))
    return str(value)


def _failure_message(error: ErrorInfo) -> str:
    if error.kind == "execution" and error.code in TIMEOUT_SQLSTATES:
        return (
            "La consulta tardó más del límite permitido. Prueba acotando el periodo, la "
            "sucursal o la categoría."
        )
    if error.kind == "validation":
        return (
            "No pude construir una consulta segura para esta pregunta "
            f"(motivo: {error.code}). Reformúlala con más detalle."
        )
    if error.kind == "generation":
        return (
            "El modelo no produjo una consulta válida tras varios intentos. Reformula la pregunta."
        )
    return (
        f"No pude obtener una respuesta fiable tras varios intentos ({error.code}). "
        "Reformula la pregunta."
    )


async def respond(state: AgentState, ctx: AgentContext) -> NodeResult:
    intent = state.get("intent")
    if intent is Intent.OUT_OF_SCOPE:
        status, answer = RunStatus.REFUSED, state.get("refusal_reason", "")
    elif intent is Intent.AMBIGUOUS and state.get("clarification") is not None:
        clarification = _require(state.get("clarification"), "clarification")
        status, answer = RunStatus.CLARIFICATION, clarification.question
    elif state.get("last_error") is not None:
        status, answer = RunStatus.FAILED, _failure_message(state["last_error"])  # type: ignore[arg-type]
    else:
        status = RunStatus.ANSWERED
        explained = state.get("explanation")
        if explained is not None:
            answer = _explanation_text(explained.explanation)
        else:
            answer = _template_summary(state.get("results", []), ctx.locale)
    return NodeResult(
        {"status": status, "answer": answer}, {"status": status.value, "answer": answer}
    )


_SUMMARY_TEXT = {
    "es": {
        "single": "{question}: {values}.",
        "many": "{question}: {count} filas; la primera es {values}.",
        "none": "{question}: la consulta no devolvió filas.",
    },
    "en": {
        "single": "{question}: {values}.",
        "many": "{question}: {count} rows; the first is {values}.",
        "none": "{question}: the query returned no rows.",
    },
}


def _template_summary(results: list[StepResult], locale: str = "es") -> str:
    """Deterministic summary built only from the data (also the explain fallback)."""
    text = _SUMMARY_TEXT["en" if locale == "en" else "es"]
    lines = []
    for result in results:
        question = result.question.strip().lstrip("¿").rstrip("?.")
        if not (result.row_count and result.columns):
            lines.append(text["none"].format(question=question))
            continue
        values = ", ".join(
            f"{c} = {_format_value(v)}" for c, v in zip(result.columns, result.rows[0], strict=True)
        )
        if result.row_count == 1 and len(result.columns) <= 4:
            lines.append(text["single"].format(question=question, values=values))
        else:
            count = _format_value(result.row_count)
            lines.append(text["many"].format(question=question, count=count, values=values))
    return "\n".join(lines)


def _localized(
    explanation: Explanation, locale: Literal["es", "en"], results: Sequence[StepResult]
) -> Explanation:
    """Grounded numbers in the UI format (ADR-0014); text cells such as product names stay."""
    quantities = quantity_values((r.columns, r.rows) for r in results)
    keep = [cell for r in results for row in r.rows for cell in row if isinstance(cell, str)]

    def fix(text: str) -> str:
        return localize_numbers(text, quantities, locale, keep=keep)

    return explanation.model_copy(
        update={
            "headline": fix(explanation.headline),
            "bullets": [fix(b) for b in explanation.bullets],
            "caveats": [fix(c) for c in explanation.caveats],
        }
    )


def _explanation_text(explanation: Explanation) -> str:
    lines = [explanation.headline, *(f"• {b}" for b in explanation.bullets)]
    lines += [f"⚠ {c}" for c in explanation.caveats]
    return "\n".join(line for line in lines if line.strip())


# ------------------------------------------------------------------------------------------------
# retrieve_schema · visualize · explain · remember (Phase 3)
# ------------------------------------------------------------------------------------------------


async def retrieve_schema(state: AgentState, ctx: AgentContext) -> NodeResult:
    context = await ctx.retriever.retrieve(state["standalone_question"])
    return NodeResult({"schema_context": context}, context.summary())


async def visualize(state: AgentState, ctx: AgentContext) -> NodeResult:
    charts: list[ChartSpec] = []
    usage = []
    for result in state.get("results", []):
        kinds, reason, picks = candidates_for(result.question, result.columns, result.rows)
        kind = kinds[0]
        if len(kinds) > 1 and ctx.chart_tiebreak:
            try:
                completion = await ctx.llm.complete(
                    prompts.visualize_messages(result.question, result.columns, kinds),
                    ChartChoice,
                    GenerationOptions(model=ctx.models.visualize, max_tokens=40),
                )
                usage.append(completion.usage)
                if completion.parsed.kind in kinds:
                    kind = completion.parsed.kind
                    reason += "; desempate del modelo"
            except StructuredOutputError as exc:
                usage.append(exc.usage)  # keep the rule's first choice
        charts.append(
            build_spec(
                kind,
                result.index,
                candidates=list(kinds),
                reason=reason,
                title=result.question,
                columns=result.columns,
                rows=result.rows,
                picks=picks,
            )
        )
    return NodeResult(
        {"charts": charts, "usage": usage},
        {
            "charts": [
                {"step": c.step, "kind": c.kind, "candidates": c.candidates, "reason": c.reason}
                for c in charts
            ]
        },
    )


def _allowed_numbers(state: AgentState) -> set[float]:
    results = state.get("results", [])
    time = state.get("time")
    extra: list[float] = []
    texts = [
        state.get("question", ""),
        state.get("standalone_question", ""),
        *state.get("assumptions", []),
    ]
    if time is not None:
        for r in time.ranges:
            extra += [
                r.start.year,
                r.start.month,
                r.start.day,
                r.last_day.year,
                r.last_day.month,
                r.last_day.day,
            ]
            extra += [float((r.start.month - 1) // 3 + 1)]
    texts += [r.question for r in results]
    return allowed_values([r.rows for r in results], extra=extra, texts=texts)


async def explain(state: AgentState, ctx: AgentContext) -> NodeResult:
    results = state.get("results", [])
    allowed = _allowed_numbers(state)
    usage = []
    offending: list[str] = []
    attempts = 0
    for attempts in range(1, ctx.max_explain_retries + 2):
        try:
            completion = await ctx.llm.complete(
                prompts.explain_messages(
                    state["standalone_question"],
                    state.get("assumptions", []),
                    results,
                    ctx.locale,
                    offending,
                ),
                Explanation,
                GenerationOptions(
                    model=ctx.models.explain, max_tokens=500, temperature=0.0, seed=7 + attempts
                ),
            )
        except StructuredOutputError as exc:
            usage.append(exc.usage)
            continue
        usage.append(completion.usage)
        text = _explanation_text(completion.parsed)
        offending = ungrounded(text, allowed)
        if not offending:
            localized = _localized(completion.parsed, ctx.locale, results)
            outcome = ExplanationResult(localized, grounded=True, fallback=False, attempts=attempts)
            return NodeResult(
                {"explanation": outcome, "usage": usage},
                {
                    "grounded": True,
                    "fallback": False,
                    "attempts": attempts,
                    "text": _explanation_text(localized),
                },
            )
    fallback = Explanation(headline=_template_summary(results, ctx.locale), bullets=[], caveats=[])
    outcome = ExplanationResult(
        fallback, grounded=True, fallback=True, attempts=attempts, ungrounded=tuple(offending)
    )
    return NodeResult(
        {"explanation": outcome, "usage": usage},
        {"grounded": True, "fallback": True, "attempts": attempts, "rejected_numbers": offending},
    )


async def remember(state: AgentState, ctx: AgentContext) -> NodeResult:
    await ctx.memory.remember(
        question=state["question"],
        standalone=state.get("standalone_question", state["question"]),
        status=RunStatus.ANSWERED.value,
    )
    return NodeResult({}, {"stored": True})
