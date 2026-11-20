"""Schema catalog + sample values + glossary + verified examples → retrievable documents."""

from __future__ import annotations

import hashlib
from collections.abc import Iterable, Mapping, Sequence
from dataclasses import dataclass
from typing import Literal

import sqlglot
from sqlalchemy import text
from sqlalchemy.ext.asyncio import AsyncEngine
from sqlglot import exp

from nexus.agent.catalog import SchemaCatalog
from nexus.agent.glossary import Glossary

DocType = Literal["table", "column", "glossary", "example"]
TEXT_TYPES = ("text", "character varying", "character")
MAX_SAMPLE_DISTINCT = 25
MAX_SAMPLE_CHARS = 60


@dataclass(frozen=True, slots=True)
class Document:
    doc_type: DocType
    ref: str  # e.g. "ventas", "ventas.estado", "ingresos", an example id
    tables: tuple[str, ...]
    title: str
    content: str  # what is embedded and full-text indexed


@dataclass(frozen=True, slots=True)
class ExampleRecord:
    id: str
    question: str
    sql: str
    tables: tuple[str, ...]


SampleValues = Mapping[tuple[str, str], Sequence[str]]


def tables_in_sql(sql: str) -> tuple[str, ...]:
    try:
        tree = sqlglot.parse_one(sql, dialect="postgres")
    except sqlglot.errors.ParseError:
        return ()
    ctes = {c.alias_or_name.lower() for c in tree.find_all(exp.CTE)}
    names = {
        t.name.lower() for t in tree.find_all(exp.Table) if t.name and t.name.lower() not in ctes
    }
    return tuple(sorted(names))


async def collect_samples(
    engine: AsyncEngine, catalog: SchemaCatalog, pii_columns: Iterable[str]
) -> dict[tuple[str, str], list[str]]:
    """Distinct values of low-cardinality text columns (never PII), most frequent first.

    These are database contents, i.e. untrusted: they are only ever rendered inside sanitized
    data blocks (see nexus.agent.prompts.data_block).
    """
    pii = {c.lower() for c in pii_columns}
    samples: dict[tuple[str, str], list[str]] = {}
    async with engine.connect() as conn:
        for table in catalog.tables.values():
            for column in table.columns:
                if f"{table.name}.{column.name}" in pii or not column.data_type.startswith(
                    TEXT_TYPES
                ):
                    continue
                if column.name in table.primary_key:
                    continue
                quoted_table = f'"{catalog.schema}"."{table.name}"'
                quoted_column = f'"{column.name}"'
                rows = (
                    await conn.execute(
                        text(
                            f"SELECT {quoted_column}, count(*) AS n FROM {quoted_table} "  # noqa: S608 — identifiers come from the catalog
                            f"WHERE {quoted_column} IS NOT NULL GROUP BY 1 ORDER BY n DESC, 1 "
                            f"LIMIT {MAX_SAMPLE_DISTINCT + 1}"
                        )
                    )
                ).all()
                if 0 < len(rows) <= MAX_SAMPLE_DISTINCT:
                    samples[(table.name, column.name)] = [
                        str(r[0])[:MAX_SAMPLE_CHARS] for r in rows
                    ]
    return samples


def _short(comment: str, limit: int = 90) -> str:
    """Comment trimmed to ``limit`` chars at a word boundary (never split on '.': "p. ej.")."""
    text = comment.rstrip(".")
    return text if len(text) <= limit else text[:limit].rsplit(" ", 1)[0] + "…"


def build_documents(
    catalog: SchemaCatalog,
    glossary: Glossary,
    samples: SampleValues,
    examples: Sequence[ExampleRecord] = (),
) -> list[Document]:
    docs: list[Document] = []
    for table in sorted(catalog.tables.values(), key=lambda t: t.name):
        columns = "; ".join(f"{c.name} ({_short(c.comment)})" for c in table.columns)
        related = sorted({fk.ref_table for fk in table.foreign_keys})
        docs.append(
            Document(
                "table",
                table.name,
                (table.name,),
                f"Tabla {table.name}",
                f"Tabla {table.name}: {table.comment} Columnas: {columns}."
                + (f" Se relaciona con: {', '.join(related)}." if related else ""),
            )
        )
        for column in table.columns:
            values = samples.get((table.name, column.name))
            sample_text = f" Valores: {', '.join(values)}." if values else ""
            docs.append(
                Document(
                    "column",
                    f"{table.name}.{column.name}",
                    (table.name,),
                    f"Columna {table.name}.{column.name}",
                    f"Columna {column.name} de la tabla {table.name} ({column.data_type}): "
                    f"{column.comment}{sample_text}",
                )
            )
    for term in glossary.metrics + glossary.entities:
        tables = set(term.tables)
        if term.sql:
            tables.update(tables_in_sql(f"SELECT {term.sql}"))
        synonyms = f" Sinónimos: {', '.join(term.synonyms)}." if term.synonyms else ""
        docs.append(
            Document(
                "glossary",
                term.term,
                tuple(sorted(t for t in tables if t in catalog.tables)),
                f"Definición de {term.term}",
                f"{term.term}: {term.definition}{synonyms}",
            )
        )
    docs.extend(
        Document("example", f"example:{ex.id}", ex.tables, "Pregunta verificada", ex.question)
        for ex in examples
    )
    return docs


def fingerprint(docs: Sequence[Document], model: str) -> str:
    digest = hashlib.sha256(model.encode())
    for doc in docs:
        digest.update(f"{doc.doc_type}|{doc.ref}|{','.join(doc.tables)}|{doc.content}".encode())
    return digest.hexdigest()
