"""Loader for the shared attack suite (used by unit, integration and agent-level tests)."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

import yaml

SUITE_PATH = Path(__file__).with_name("attacks.yaml")

RETAIL_TABLES = frozenset(
    {
        "regiones", "sucursales", "categorias", "productos", "clientes",
        "empleados", "ventas", "detalle_ventas", "inventario", "devoluciones",
    }
)  # fmt: skip


@dataclass(frozen=True)
class SqlAttack:
    id: str
    sql: str
    code: str
    destructive: bool


@dataclass(frozen=True)
class Benign:
    id: str
    sql: str
    limit: int


@dataclass(frozen=True)
class PromptAttack:
    id: str
    question: str


def _load() -> dict[str, list[dict[str, object]]]:
    data: dict[str, list[dict[str, object]]] = yaml.safe_load(
        SUITE_PATH.read_text(encoding="utf-8")
    )
    return data


_DATA = _load()
SQL_ATTACKS = [SqlAttack(**c) for c in _DATA["sql_attacks"]]  # type: ignore[arg-type]
BENIGN = [Benign(**c) for c in _DATA["benign"]]  # type: ignore[arg-type]
PROMPT_ATTACKS = [PromptAttack(**c) for c in _DATA["prompt_attacks"]]  # type: ignore[arg-type]
