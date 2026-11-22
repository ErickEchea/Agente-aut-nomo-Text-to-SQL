"""The golden set: questions, gold SQL and the frozen expected results (ADR-0015).

``bench/golden/<difficulty>.yaml`` holds the questions; ``bench/golden/expected.json`` holds the
result of each gold query, frozen with ``nexus-bench freeze``. Every frozen entry records the
SHA-256 of its gold SQL and the demo dataset version, so editing a query or regenerating the data
without re-freezing is caught by a unit test instead of silently scoring against stale answers.
"""

from __future__ import annotations

import hashlib
import json
import re
from collections import Counter
from enum import StrEnum
from pathlib import Path
from typing import Literal, Self

import sqlglot
import yaml
from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator
from sqlglot import exp

EXPECTED_FILE = "expected.json"
_ID = re.compile(r"^[emha]\d{3}$")


class Difficulty(StrEnum):
    EASY = "easy"
    MEDIUM = "medium"
    HARD = "hard"
    AMBIGUOUS = "ambiguous"


class GoldenItem(BaseModel):
    model_config = ConfigDict(frozen=True, extra="forbid")

    id: str
    question: str = Field(min_length=3)
    difficulty: Difficulty
    tags: tuple[str, ...] = ()
    gold_sql: tuple[str, ...] = ()
    order_matters: bool = False
    expected_behavior: Literal["answer", "clarify"] = "answer"
    # Earlier questions of the same conversation, asked first; only the last turn is scored.
    history: tuple[str, ...] = ()
    note: str = ""

    @field_validator("gold_sql", mode="before")
    @classmethod
    def _one_or_many(cls, value: object) -> object:
        return (value,) if isinstance(value, str) else value

    @model_validator(mode="after")
    def _consistent(self) -> Self:
        if not _ID.match(self.id) or self.id[0] != self.difficulty.value[0]:
            raise ValueError(f"{self.id}: id must be <{self.difficulty.value[0]}NNN>")
        if self.expected_behavior == "clarify":
            if self.gold_sql or self.difficulty is not Difficulty.AMBIGUOUS:
                raise ValueError(f"{self.id}: clarify items are ambiguous and have no gold SQL")
        elif not self.gold_sql:
            raise ValueError(f"{self.id}: answer items need gold_sql")
        return self

    @property
    def answers(self) -> bool:
        return self.expected_behavior == "answer"

    @property
    def sql_digest(self) -> str:
        """SHA-256 of the gold SQL, whitespace collapsed (re-indenting needs no re-freeze)."""
        canonical = "\n;\n".join(" ".join(sql.split()) for sql in self.gold_sql)
        return hashlib.sha256(canonical.encode()).hexdigest()

    @property
    def gold_tables(self) -> frozenset[str]:
        """Base tables the gold SQL reads (CTE names excluded), for retrieval recall."""
        tables: set[str] = set()
        for sql in self.gold_sql:
            tree = sqlglot.parse_one(sql, read="postgres")
            ctes = {cte.alias_or_name.lower() for cte in tree.find_all(exp.CTE)}
            tables |= {t.name.lower() for t in tree.find_all(exp.Table) if t.name} - ctes
        return frozenset(tables)


class _File(BaseModel):
    model_config = ConfigDict(extra="forbid")

    difficulty: Difficulty
    items: list[dict[str, object]]


class GoldenSet(BaseModel):
    model_config = ConfigDict(frozen=True)

    items: tuple[GoldenItem, ...]

    @classmethod
    def load(cls, directory: Path) -> GoldenSet:
        items: list[GoldenItem] = []
        for path in sorted(directory.glob("*.yaml")):
            raw = _File.model_validate(yaml.safe_load(path.read_text(encoding="utf-8")))
            items += [
                GoldenItem.model_validate({**item, "difficulty": raw.difficulty})
                for item in raw.items
            ]
        duplicated = [key for key, n in Counter(i.id for i in items).items() if n > 1]
        if duplicated:
            raise ValueError(f"duplicated golden ids: {duplicated}")
        return cls(items=tuple(sorted(items, key=lambda i: i.id)))

    def by_id(self) -> dict[str, GoldenItem]:
        return {item.id: item for item in self.items}

    def counts(self) -> dict[str, int]:
        found = Counter(item.difficulty.value for item in self.items)
        return {d.value: found.get(d.value, 0) for d in Difficulty}

    def subset(self, ids: set[str] | None) -> tuple[GoldenItem, ...]:
        return self.items if ids is None else tuple(i for i in self.items if i.id in ids)


class FrozenResult(BaseModel):
    """One gold query's result as canonical cell tokens (see nexus.bench.compare.normalize)."""

    model_config = ConfigDict(frozen=True)

    columns: tuple[str, ...]
    rows: tuple[tuple[str, ...], ...]


class FrozenItem(BaseModel):
    model_config = ConfigDict(frozen=True)

    sql_sha256: str
    results: tuple[FrozenResult, ...]


class ExpectedResults(BaseModel):
    model_config = ConfigDict(frozen=True)

    dataset_version: str
    as_of: str
    items: dict[str, FrozenItem]

    @classmethod
    def load(cls, directory: Path) -> ExpectedResults:
        return cls.model_validate_json((directory / EXPECTED_FILE).read_text(encoding="utf-8"))

    def save(self, directory: Path) -> Path:
        path = directory / EXPECTED_FILE
        payload = self.model_dump(mode="json")
        path.write_text(json.dumps(payload, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
        return path

    def stale(self, golden: GoldenSet) -> list[str]:
        """Answer items whose frozen result is missing or was frozen from a different gold SQL."""
        out = []
        for item in golden.items:
            if not item.answers:
                continue
            frozen = self.items.get(item.id)
            if frozen is None or frozen.sql_sha256 != item.sql_digest:
                out.append(item.id)
        return out
