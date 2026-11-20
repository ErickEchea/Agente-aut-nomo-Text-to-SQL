"""Business glossary (data/glossary.yaml): authoritative metric and time definitions.

Besides prompt context, a term can declare ``requires``: tables and string literals that SQL
answering a question about that term must contain. ``verify_results`` enforces them
deterministically, so a model that forgets "excluir devoluciones" is sent back to repair instead
of silently being wrong.
"""

from __future__ import annotations

import re
import unicodedata
from collections.abc import Sequence
from dataclasses import dataclass, field
from pathlib import Path

import sqlglot
import yaml
from sqlglot import exp


@dataclass(frozen=True, slots=True)
class SqlRequirement:
    tables: tuple[str, ...] = ()
    literals: tuple[str, ...] = ()
    message: str = ""


@dataclass(frozen=True, slots=True)
class GlossaryTerm:
    term: str
    synonyms: tuple[str, ...]
    definition: str
    sql: str | None = None
    requires: SqlRequirement | None = None
    maps_to: str | None = None  # table an entity term refers to

    @property
    def tables(self) -> tuple[str, ...]:
        """Tables a question using this term needs (required tables + the mapped entity table)."""
        tables = list(self.requires.tables) if self.requires else []
        if self.maps_to:
            tables.append(self.maps_to)
        return tuple(dict.fromkeys(tables))

    @property
    def phrases(self) -> tuple[str, ...]:
        return (self.term, *self.synonyms)


@dataclass(frozen=True, slots=True)
class Glossary:
    currency: str
    metrics: tuple[GlossaryTerm, ...]
    entities: tuple[GlossaryTerm, ...] = field(default_factory=tuple)

    def render(self, terms: Sequence[GlossaryTerm] | None = None) -> str:
        """All terms, or only ``terms`` (the ones retrieval found relevant)."""
        lines = [f"Moneda: {self.currency}."]
        for term in self.metrics + self.entities if terms is None else terms:
            synonyms = f" (sinónimos: {', '.join(term.synonyms)})" if term.synonyms else ""
            lines.append(f"- {term.term}{synonyms}: {term.definition}")
            if term.sql:
                lines.append(f"  SQL de referencia: {' '.join(term.sql.split())}")
        return "\n".join(lines)

    def terms_in(self, question: str) -> list[GlossaryTerm]:
        """Terms mentioned in the question; a phrase inside a longer matched phrase does not count
        (e.g. "ingresos" inside "ingresos brutos")."""
        text = _normalize(question)
        matches: list[tuple[int, int, GlossaryTerm]] = []
        for term in self.metrics + self.entities:
            for phrase in term.phrases:
                pattern = rf"\b{re.escape(_normalize(phrase))}\b"
                matches.extend((m.start(), m.end(), term) for m in re.finditer(pattern, text))
        matches.sort(key=lambda m: (m[0] - m[1], m[0]))  # longest first
        kept: list[tuple[int, int, GlossaryTerm]] = []
        for start, end, term in matches:
            if not any(s <= start and end <= e for s, e, _ in kept):
                kept.append((start, end, term))
        return list(dict.fromkeys(term for _, _, term in kept))

    def violations(self, question: str, sql: str) -> list[str]:
        """Messages for each ``requires`` rule of a mentioned term that ``sql`` breaks."""
        required = [t.requires for t in self.terms_in(question) if t.requires is not None]
        if not required:
            return []
        try:
            tree = sqlglot.parse_one(sql, dialect="postgres")
        except sqlglot.errors.ParseError:
            return []  # the validator already guarantees parseable SQL
        tables = {t.name.lower() for t in tree.find_all(exp.Table)}
        literals = {str(lit.this).lower() for lit in tree.find_all(exp.Literal) if lit.is_string}
        problems = []
        for rule in required:
            missing_tables = [t for t in rule.tables if t.lower() not in tables]
            missing_literals = [lit for lit in rule.literals if lit.lower() not in literals]
            if missing_tables or missing_literals:
                problems.append(rule.message)
        return list(dict.fromkeys(problems))


def _normalize(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text.lower())
    return "".join(c for c in decomposed if not unicodedata.combining(c))


def _as_list(value: object) -> list[object]:
    return value if isinstance(value, list) else []


def _terms(items: list[dict[str, object]]) -> tuple[GlossaryTerm, ...]:
    out = []
    for item in items:
        definition = str(item.get("definition") or f"Tabla {item.get('maps_to', '')}").strip()
        raw_requires = item.get("requires")
        requires = None
        if isinstance(raw_requires, dict):
            requires = SqlRequirement(
                tables=tuple(str(t) for t in _as_list(raw_requires.get("tables"))),
                literals=tuple(str(lit) for lit in _as_list(raw_requires.get("literals"))),
                message=" ".join(str(raw_requires.get("message", "")).split()),
            )
        out.append(
            GlossaryTerm(
                term=str(item["term"]),
                synonyms=tuple(str(s) for s in _as_list(item.get("synonyms"))),
                definition=" ".join(definition.split()),
                sql=str(item["sql"]) if item.get("sql") else None,
                requires=requires,
                maps_to=str(item["maps_to"]).split(".")[-1] if item.get("maps_to") else None,
            )
        )
    return tuple(out)


def load_glossary(path: Path) -> Glossary:
    data = yaml.safe_load(path.read_text(encoding="utf-8"))
    return Glossary(
        currency=str(data.get("currency", "USD")),
        metrics=_terms(data.get("metrics", [])),
        entities=_terms(data.get("entities", [])),
    )
