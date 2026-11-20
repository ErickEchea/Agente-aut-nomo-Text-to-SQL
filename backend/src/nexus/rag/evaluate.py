"""``nexus-eval-retrieval``: measure schema retrieval against bench/retrieval/questions.yaml.

Metrics per configuration (embedding profile x search strategy):
- recall@5: share of gold tables among the top-5 *ranked* tables (pure retrieval, before the
  glossary-forced tables and FK expansion);
- complete: share of questions whose final context contains *every* gold table (what the SQL needs);
- tables/question: context size sent to the model (smaller = cheaper, less distraction);
- latency: mean retrieval time per question.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import statistics
import time
from collections.abc import Sequence
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import yaml
from pydantic import Field
from pydantic_settings import BaseSettings, SettingsConfigDict
from sqlalchemy.ext.asyncio import async_sessionmaker

from nexus.agent.catalog import introspect
from nexus.agent.glossary import load_glossary
from nexus.config import DatabaseSettings, OllamaSettings
from nexus.db.engines import create_engine
from nexus.llm.ollama import OllamaProvider
from nexus.rag.documents import collect_samples
from nexus.rag.embeddings import Embedder, EmbeddingProfile, profile_for
from nexus.rag.indexer import ensure_index
from nexus.rag.retriever import HybridRetriever, RetrievedExample
from nexus.rag.store import PgDocumentStore

EVAL_KEY = "retrieval-eval"


class EvalSettings(BaseSettings):
    model_config = SettingsConfigDict(
        env_prefix="NEXUS_", env_nested_delimiter="__", extra="ignore"
    )
    app_db: DatabaseSettings
    demo_db: DatabaseSettings
    ollama: OllamaSettings = Field(default_factory=OllamaSettings)


@dataclass(frozen=True, slots=True)
class QuestionResult:
    question: str
    gold: list[str]
    ranked: list[str]
    selected: list[str]
    recall_at_5: float
    complete: bool
    seconds: float


@dataclass(frozen=True, slots=True)
class ConfigResult:
    name: str
    strategy: str
    recall_at_5: float
    complete_rate: float
    tables_per_question: float
    latency_ms: float
    misses: list[str]


def _score(results: Sequence[QuestionResult], name: str, strategy: str) -> ConfigResult:
    return ConfigResult(
        name=name,
        strategy=strategy,
        recall_at_5=round(statistics.mean(r.recall_at_5 for r in results), 3),
        complete_rate=round(sum(r.complete for r in results) / len(results), 3),
        tables_per_question=round(statistics.mean(len(r.selected) for r in results), 2),
        latency_ms=round(statistics.mean(r.seconds for r in results) * 1000, 1),
        misses=[
            f"{r.question} → falta {sorted(set(r.gold) - set(r.selected))}"
            for r in results
            if not r.complete
        ],
    )


async def _no_examples(_: Sequence[str]) -> list[RetrievedExample]:
    return []


def load_questions(path: Path) -> list[dict[str, Any]]:
    data: dict[str, list[dict[str, Any]]] = yaml.safe_load(path.read_text(encoding="utf-8"))
    return data["questions"]


async def run(
    questions_path: Path, glossary_path: Path, models: list[str], out_md: Path, out_json: Path
) -> list[ConfigResult]:
    settings = EvalSettings()
    questions = load_questions(questions_path)
    app_engine = create_engine(settings.app_db, application_name="nexus-eval")
    demo_engine = create_engine(settings.demo_db, application_name="nexus-eval-reader")
    llm = OllamaProvider(
        str(settings.ollama.base_url), settings.ollama.llm_model, models[0], timeout_s=300
    )
    store = PgDocumentStore(async_sessionmaker(app_engine, expire_on_commit=False))
    catalog = await introspect(demo_engine)
    glossary = load_glossary(glossary_path)
    samples = await collect_samples(demo_engine, catalog, [])

    profiles: list[EmbeddingProfile] = []
    for model in models:
        base = profile_for(model)
        profiles.append(base)
        if base.query_template != "{text}" or base.document_template != "{text}":
            profiles.append(base.raw())

    results: list[ConfigResult] = []
    lexical_done = False
    for profile in profiles:
        embedder = Embedder(llm, profile)
        key = f"{EVAL_KEY}:{profile.name}"
        await ensure_index(
            store=store, embedder=embedder, catalog=catalog, glossary=glossary, samples=samples,
            examples=[], connection_key=key, force=True,
        )  # fmt: skip
        strategies = [("hybrid", True, True, True), ("dense", True, False, False)]
        if not lexical_done:
            strategies.append(("lexical+fuzzy", False, True, True))
            lexical_done = True
        for strategy, dense, lexical, fuzzy in strategies:
            retriever = HybridRetriever(
                store=store, embedder=embedder, catalog=catalog, glossary=glossary, connection_key=key,
                samples=samples, load_examples=_no_examples, use_dense=dense, use_lexical=lexical, use_fuzzy=fuzzy,
            )  # fmt: skip
            per_question: list[QuestionResult] = []
            for item in questions:
                started = time.perf_counter()
                context = await retriever.retrieve(item["q"])
                elapsed = time.perf_counter() - started
                gold = list(item["tables"])
                top5 = [r.name for r in context.ranked[:5]]
                per_question.append(
                    QuestionResult(
                        question=item["q"],
                        gold=gold,
                        ranked=top5,
                        selected=list(context.tables),
                        recall_at_5=len(set(gold) & set(top5)) / len(gold),
                        complete=set(gold) <= set(context.tables),
                        seconds=elapsed,
                    )
                )
            name = profile.name if strategy != "lexical+fuzzy" else "— (sin embeddings)"
            results.append(_score(per_question, name, strategy))
            print(
                f"{name:32s} {strategy:14s} recall@5={results[-1].recall_at_5:.3f} complete={results[-1].complete_rate:.3f}"
            )

    await app_engine.dispose()
    await demo_engine.dispose()
    _write_report(results, len(questions), out_md, out_json)
    return results


def _write_report(results: list[ConfigResult], n: int, out_md: Path, out_json: Path) -> None:
    out_json.parent.mkdir(parents=True, exist_ok=True)
    out_json.write_text(
        json.dumps([asdict(r) for r in results], ensure_ascii=False, indent=2), encoding="utf-8"
    )
    best = max(results, key=lambda r: (r.complete_rate, r.recall_at_5, -r.tables_per_question))
    lines = [
        "# Schema retrieval evaluation",
        "",
        f"Generated by `make eval-retrieval` on {datetime.now(UTC):%Y-%m-%d %H:%M} UTC over {n} questions "
        "([`bench/retrieval/questions.yaml`](../bench/retrieval/questions.yaml)).",
        "",
        "- **recall@5**: share of gold tables in the top-5 ranked tables (pure retrieval).",
        "- **complete**: share of questions whose final context has *every* gold table "
        "(after glossary-forced tables and FK join expansion) — what SQL generation needs.",
        "- **tables/q**: context size sent to the model (the full schema has 10 tables).",
        "",
        "| Embedding profile | Strategy | recall@5 | complete | tables/q | latency (ms) |",
        "|---|---|---:|---:|---:|---:|",
    ]
    lines += [
        f"| {r.name} | {r.strategy} | {r.recall_at_5:.3f} | {r.complete_rate:.3f} | {r.tables_per_question} | {r.latency_ms} |"
        for r in results
    ]
    lines += [
        "",
        f"**Best:** {best.name} · {best.strategy}.",
        "",
        "## Misses of the best configuration",
        "",
    ]
    lines += [f"- {m}" for m in best.misses] or ["- none"]
    out_md.write_text("\n".join(lines) + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(prog="nexus-eval-retrieval")
    parser.add_argument("--questions", type=Path, default=Path("../bench/retrieval/questions.yaml"))
    parser.add_argument("--glossary", type=Path, default=Path("../data/glossary.yaml"))
    parser.add_argument(
        "--models", nargs="+", default=["qwen3-embedding:0.6b", "embeddinggemma-2:latest"]
    )
    parser.add_argument("--out", type=Path, default=Path("../docs/retrieval-eval.md"))
    parser.add_argument("--json", type=Path, default=Path("../bench/results/retrieval-eval.json"))
    args = parser.parse_args()
    asyncio.run(run(args.questions, args.glossary, args.models, args.out, args.json))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
