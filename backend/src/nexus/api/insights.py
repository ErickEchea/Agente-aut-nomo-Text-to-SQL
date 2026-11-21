"""Explainability and optimization of an answered step (Phase 5).

Both work from the step's stored SQL, re-validated against the source's current policy before any
use, so a schema that changed since the run (or tampered data) cannot reach the database.
"""

from __future__ import annotations

import uuid
from typing import Literal

from fastapi import APIRouter, HTTPException, Query, status
from pydantic import BaseModel

from nexus.api.deps import AuthenticatedUser, CurrentUser, Services, Session, enforce_rate_limit
from nexus.datasources.registry import SourceError, SourceRuntime
from nexus.db.models import Role, Run
from nexus.runs.schemas import RunResult, StepOut
from nexus.sql.annotate import annotate
from nexus.sql.executor import QueryExecutionError
from nexus.sql.optimizer import analyze
from nexus.sql.validator import SQLValidationError, ValidatedSQL, validate_sql

router = APIRouter(prefix="/api/runs/{run_id}/steps/{step}", tags=["insights"])


class ClauseOut(BaseModel):
    kind: str
    scope: str
    start: int
    end: int
    title: str
    details: list[str]
    rules: list[str]


class AnnotationOut(BaseModel):
    sql: str
    dialect: str
    clauses: list[ClauseOut]


class PlanStepOut(BaseModel):
    depth: int
    operation: str
    table: str | None
    detail: str
    rows: float | None
    cost: float | None


class FindingOut(BaseModel):
    severity: Literal["high", "medium", "info"]
    code: str
    table: str | None
    rows: int | None
    columns: list[str]


class SuggestionOut(BaseModel):
    table: str
    columns: list[str]
    ddl: str
    reason: str
    cost_before: float | None
    cost_after: float | None
    improvement: float | None
    used_by_planner: bool | None


class OptimizationOut(BaseModel):
    engine: str
    supports_costs: bool
    total_cost: float | None
    plan: list[PlanStepOut]
    findings: list[FindingOut]
    suggestions: list[SuggestionOut]


async def _step(
    session: Session, services: Services, user: CurrentUser, run_id: uuid.UUID, step: int
) -> tuple[Run, StepOut, SourceRuntime, ValidatedSQL]:
    run = await session.get(Run, run_id)
    if run is None or (run.user_id != user.id and user.role is not Role.ADMIN):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "run not found")
    result = RunResult.model_validate(run.result) if run.result else None
    found = next((s for s in result.results if s.index == step), None) if result else None
    if found is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "step not found")
    try:
        source = await services.registry.get(run.connection_key)
    except SourceError as exc:
        raise HTTPException(status.HTTP_503_SERVICE_UNAVAILABLE, str(exc)) from None
    try:
        validated = validate_sql(found.sql, source.policy)
    except SQLValidationError as exc:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, f"stored SQL no longer validates: {exc.code}"
        ) from None
    return run, found, source, validated


@router.get("/annotation")
async def get_annotation(
    run_id: uuid.UUID,
    step: int,
    user: AuthenticatedUser,
    session: Session,
    services: Services,
    *,
    locale: Literal["es", "en"] = Query(default="es"),
) -> AnnotationOut:
    _, found, source, validated = await _step(session, services, user, run_id, step)
    annotated = annotate(
        validated.sql,
        dialect=source.profile.sqlglot,
        catalog=source.catalog,
        glossary=source.glossary,
        question=found.question,
        locale=locale,
    )
    return AnnotationOut(
        sql=annotated.sql,
        dialect=source.profile.label,
        clauses=[
            ClauseOut(
                kind=c.kind,
                scope=c.scope,
                start=c.start,
                end=c.end,
                title=c.title,
                details=list(c.details),
                rules=list(c.rules),
            )
            for c in annotated.clauses
        ],
    )


@router.post("/optimize")
async def optimize(
    run_id: uuid.UUID, step: int, user: AuthenticatedUser, session: Session, services: Services
) -> OptimizationOut:
    enforce_rate_limit(services, "default", str(user.id))
    _, _, source, validated = await _step(session, services, user, run_id, step)
    try:
        report = await analyze(
            source.executor,
            validated,
            kind=source.profile.kind,
            dialect=source.profile.sqlglot,
            catalog=source.catalog,
            rows=source.rows,
            indexes=source.indexes,
        )
    except QueryExecutionError as exc:
        raise HTTPException(
            status.HTTP_422_UNPROCESSABLE_CONTENT, f"the engine could not plan this query: {exc}"
        ) from None
    return OptimizationOut(
        engine=report.engine,
        supports_costs=report.supports_costs,
        total_cost=report.total_cost,
        plan=[
            PlanStepOut(
                depth=p.depth,
                operation=p.operation,
                table=p.table,
                detail=p.detail,
                rows=p.rows,
                cost=p.cost,
            )
            for p in report.plan
        ],
        findings=[
            FindingOut(
                severity=f.severity,
                code=f.code,
                table=f.table,
                rows=f.rows,
                columns=list(f.columns),
            )
            for f in report.findings
        ],
        suggestions=[
            SuggestionOut(
                table=s.table,
                columns=list(s.columns),
                ddl=s.ddl,
                reason=s.reason,
                cost_before=s.cost_before,
                cost_after=s.cost_after,
                improvement=s.improvement,
                used_by_planner=s.used_by_planner,
            )
            for s in report.suggestions
        ],
    )
