"""The frontend's API types are generated from a committed OpenAPI snapshot; it must match the routes."""

from __future__ import annotations

from pathlib import Path

from nexus.openapi import openapi_schema, render

SNAPSHOT = Path(__file__).resolve().parents[3] / "frontend" / "src" / "api" / "openapi.json"


def test_snapshot_matches_the_routes() -> None:
    assert SNAPSHOT.read_text(encoding="utf-8") == render(), (
        "OpenAPI snapshot is stale: run `make api-types` and commit the result"
    )


def test_contract_exposes_the_typed_run_result() -> None:
    schemas = openapi_schema()["components"]["schemas"]
    assert {"RunResult", "StepOut", "ChartSpec", "DashboardOut", "ConnectionOut"} <= set(schemas)
