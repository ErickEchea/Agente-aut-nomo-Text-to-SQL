"""Hybrid retrieval: dense + lexical + trigram rankings fused with RRF, then mapped to tables."""

from __future__ import annotations

import unicodedata
from collections import defaultdict
from collections.abc import Awaitable, Callable, Mapping, Sequence
from dataclasses import dataclass, field

import structlog

from nexus.agent.catalog import SchemaCatalog
from nexus.agent.glossary import Glossary, GlossaryTerm
from nexus.llm import LLMError
from nexus.rag.embeddings import Embedder
from nexus.rag.joins import JoinEdge, connect
from nexus.rag.store import Hit, PgDocumentStore

logger = structlog.get_logger("nexus.rag")

RRF_K = 60
# How much each document type contributes to its tables' scores.
TYPE_WEIGHT = {"table": 1.0, "column": 0.8, "glossary": 1.2, "example": 1.5}


@dataclass(frozen=True, slots=True)
class RankedTable:
    name: str
    score: float


@dataclass(frozen=True, slots=True)
class RetrievedExample:
    ref: str
    question: str
    sql: str


@dataclass(frozen=True, slots=True)
class SchemaContext:
    tables: tuple[str, ...]
    joins: tuple[JoinEdge, ...]
    ranked: tuple[RankedTable, ...]
    terms: tuple[GlossaryTerm, ...]
    examples: tuple[RetrievedExample, ...] = ()
    forced_tables: tuple[str, ...] = ()
    strategy: str = "hybrid"
    samples: dict[tuple[str, str], list[str]] = field(default_factory=dict)

    def summary(self) -> dict[str, object]:
        return {
            "strategy": self.strategy,
            "tables": list(self.tables),
            "ranked": [{"table": r.name, "score": round(r.score, 4)} for r in self.ranked[:8]],
            "joins": [j.condition() for j in self.joins],
            "terms": [t.term for t in self.terms],
            "examples": [e.question for e in self.examples],
            "forced_tables": list(self.forced_tables),
        }


def reciprocal_rank_fusion(
    rankings: Sequence[Sequence[Hit]], k: int = RRF_K
) -> list[tuple[Hit, float]]:
    """Standard RRF: score(d) = Σ 1 / (k + rank_i(d)). Ties keep first-seen order."""
    scores: dict[tuple[str, str], float] = defaultdict(float)
    first: dict[tuple[str, str], Hit] = {}
    for ranking in rankings:
        for rank, hit in enumerate(ranking, start=1):
            key = (hit.doc_type, hit.ref)
            scores[key] += 1.0 / (k + rank)
            first.setdefault(key, hit)
    return sorted(((first[key], s) for key, s in scores.items()), key=lambda item: -item[1])


ExampleLoader = Callable[[Sequence[str]], Awaitable[list[RetrievedExample]]]
MIN_VALUE_CHARS = 4


def _normalize(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text.lower())
    plain = "".join(c for c in decomposed if not unicodedata.combining(c))
    # Punctuation and underscores separate words: "Costa?" matches "Costa", billetera_movil too.
    return " ".join("".join(c if c.isalnum() else " " for c in plain).split())


def link_values(
    question: str,
    samples: Mapping[tuple[str, str], Sequence[str]],
    table_scores: Mapping[str, float],
) -> list[str]:
    """Tables whose categorical values appear verbatim (as whole words) in the question.

    When a value exists in several tables (e.g. a city in ``clientes`` and ``sucursales``), only
    the table retrieval already ranks highest is linked, to avoid bloating the context.
    """
    text = f" {_normalize(question)} "
    by_value: dict[str, list[str]] = defaultdict(list)
    for (table, _column), values in samples.items():
        for value in values:
            norm = _normalize(value)
            if len(norm) >= MIN_VALUE_CHARS and f" {norm} " in text:
                by_value[norm].append(table)
    linked: list[str] = []
    for tables in by_value.values():
        best = max(sorted(set(tables)), key=lambda t: table_scores.get(t, 0.0))
        if best not in linked:
            linked.append(best)
    return linked


class HybridRetriever:
    def __init__(
        self,
        *,
        store: PgDocumentStore,
        embedder: Embedder,
        catalog: SchemaCatalog,
        glossary: Glossary,
        connection_key: str,
        samples: dict[tuple[str, str], list[str]],
        load_examples: ExampleLoader,
        k: int = 20,
        max_tables: int = 4,
        use_dense: bool = True,
        use_lexical: bool = True,
        use_fuzzy: bool = True,
    ) -> None:
        self._store = store
        self._embedder = embedder
        self._catalog = catalog
        self._glossary = glossary
        self._key = connection_key
        self._samples = samples
        self._load_examples = load_examples
        self._k = k
        self._max_tables = max_tables
        self._flags = (use_dense, use_lexical, use_fuzzy)

    @property
    def strategy(self) -> str:
        names = ("dense", "lexical", "fuzzy")
        active = [n for n, on in zip(names, self._flags, strict=True) if on]
        return "hybrid" if len(active) == len(names) else "+".join(active)

    async def rank(self, question: str) -> tuple[list[tuple[Hit, float]], bool]:
        """Fused ranking and whether dense search had to be skipped (embeddings unavailable)."""
        model = self._embedder.profile.model
        use_dense, use_lexical, use_fuzzy = self._flags
        rankings: list[list[Hit]] = []
        dense_failed = False
        if use_dense:
            try:
                vector = await self._embedder.embed_query(question)
                rankings.append(await self._store.dense(self._key, model, vector, self._k))
            except LLMError:
                # Embeddings unavailable: degrade to lexical + fuzzy rather than failing the run.
                dense_failed = True
                logger.warning("rag.dense_unavailable", connection=self._key)
        if use_lexical:
            rankings.append(await self._store.lexical(self._key, model, question, self._k))
        if use_fuzzy:
            rankings.append(await self._store.fuzzy(self._key, model, question, self._k // 2))
        return reciprocal_rank_fusion(rankings), dense_failed

    async def retrieve(self, question: str) -> SchemaContext:
        fused, dense_failed = await self.rank(question)
        table_scores: dict[str, float] = defaultdict(float)
        for hit, score in fused:
            weight = TYPE_WEIGHT.get(hit.doc_type, 1.0)
            for table in hit.tables:
                if table in self._catalog.tables:
                    table_scores[table] += weight * score
        ranked = tuple(
            RankedTable(name, s) for name, s in sorted(table_scores.items(), key=lambda i: -i[1])
        )

        # Deterministic additions: tables required by business terms the question uses, and tables
        # whose categorical values the question mentions ("Costa" → regiones).
        mentioned = self._glossary.terms_in(question)
        scores = {r.name: r.score for r in ranked}
        forced = tuple(
            dict.fromkeys(
                [
                    *(t for term in mentioned for t in term.tables),
                    *link_values(question, self._samples, scores),
                ]
            )
        )
        top = [r.name for r in ranked[: self._max_tables]]
        tables, joins = connect(self._catalog, [*top, *(t for t in forced if t not in top)])
        strategy = self.strategy + (" (sin embeddings)" if dense_failed else "")
        if not tables:  # empty or missing index: never starve the model of schema
            tables, joins = connect(self._catalog, sorted(self._catalog.tables))
            strategy = "full-schema (índice vacío)"

        glossary_refs = [hit.ref for hit, _ in fused if hit.doc_type == "glossary"][:3]
        terms = tuple(
            dict.fromkeys(
                [
                    *mentioned,
                    *(
                        t
                        for t in self._glossary.metrics + self._glossary.entities
                        if t.term in glossary_refs
                    ),
                ]
            )
        )
        example_refs = [hit.ref for hit, _ in fused if hit.doc_type == "example"][:2]
        examples = tuple(await self._load_examples(example_refs)) if example_refs else ()
        samples = {key: values for key, values in self._samples.items() if key[0] in tables}
        return SchemaContext(
            tables=tuple(tables),
            joins=tuple(joins),
            ranked=ranked,
            terms=terms,
            examples=examples,
            forced_tables=forced,
            strategy=strategy,
            samples=samples,
        )
