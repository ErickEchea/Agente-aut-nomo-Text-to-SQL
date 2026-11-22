"""``nexus-bench``: freeze the golden answers, run configurations, render the report, gate CI.

Runs inside the backend image (``make bench`` uses ``docker compose run`` with ``bench/`` and
``docs/`` mounted), so the agent, database roles and Ollama are exactly those of the API.
"""

from __future__ import annotations

import argparse
import asyncio
import datetime as dt
import math
import sys
from collections.abc import Awaitable, Callable, Sequence
from pathlib import Path

import httpx
import yaml
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker

from nexus.agent.catalog import introspect
from nexus.agent.graph import build_graph
from nexus.agent.state import AgentContext, AuditSink, EventSink, MemorySink
from nexus.bench.compare import normalize
from nexus.bench.golden import (
    ExpectedResults,
    FrozenItem,
    FrozenResult,
    GoldenItem,
    GoldenSet,
)
from nexus.bench.metrics import select_default, summarize
from nexus.bench.report import eligible_configs, latest_by_config, render
from nexus.bench.runner import BenchConfig, ItemOutcome, load_configs, run_items
from nexus.bench.store import (
    RunRecord,
    fail_run,
    finish_run,
    read_records,
    start_run,
    write_record,
)
from nexus.config import Settings, get_settings
from nexus.datasources.registry import ConnectionRegistry, SourceRuntime, builtin_spec
from nexus.db.engines import create_engine
from nexus.db.models import VerifiedExample
from nexus.demo import DATASET_VERSION
from nexus.llm.ollama import OllamaProvider
from nexus.memory.store import question_key
from nexus.observability.logging import configure_logging
from nexus.rag.embeddings import Embedder, profile_for
from nexus.rag.store import PgDocumentStore
from nexus.sql.executor import ReadOnlyExecutor
from nexus.sql.validator import ValidationPolicy, validate_sql

FREEZE_MAX_ROWS = 1000
OVERLAP_COSINE = 0.92


class BenchError(RuntimeError):
    """A precondition failed (stale golden answers, missing model, leaked example...)."""


# ---- freeze ----------------------------------------------------------------------------------


async def freeze(golden_dir: Path, settings: Settings) -> int:
    """Run every gold query (validated, read-only) and store the canonical results."""
    golden = GoldenSet.load(golden_dir)
    engine = create_engine(settings.demo_db, application_name="nexus-bench-freeze")
    executor = ReadOnlyExecutor(engine, statement_timeout_ms=120_000, max_rows=FREEZE_MAX_ROWS)
    spec = builtin_spec(settings)
    items: dict[str, FrozenItem] = {}
    try:
        catalog = await introspect(engine, spec.schema)
        tables = set(catalog.table_names)
        policy = ValidationPolicy(
            allowed_tables=frozenset(tables),
            allowed_schemas=frozenset({spec.schema}),
            max_rows=FREEZE_MAX_ROWS,
        )
        for item in golden.items:
            if not item.answers:
                continue
            results = []
            for sql in item.gold_sql:
                validated = validate_sql(sql, policy)
                result = await executor.execute(validated)
                if result.truncated or result.row_count == 0:
                    raise BenchError(f"{item.id}: gold result has {result.row_count} rows")
                results.append(
                    FrozenResult(
                        columns=result.columns,
                        rows=tuple(tuple(normalize(c) for c in row) for row in result.rows),
                    )
                )
            items[item.id] = FrozenItem(sql_sha256=item.sql_digest, results=tuple(results))
            print(f"{item.id}  {sum(len(r.rows) for r in results):4d} rows  {item.question[:70]}")
    finally:
        await engine.dispose()
    as_of = settings.agent.as_of.isoformat() if settings.agent.as_of else ""
    path = ExpectedResults(dataset_version=DATASET_VERSION, as_of=as_of, items=items).save(
        golden_dir
    )
    print(f"froze {len(items)} answers into {path}")
    return 0


# ---- run -------------------------------------------------------------------------------------


def _select_items(
    golden: GoldenSet, subset: str, ci_items: Sequence[str]
) -> tuple[GoldenItem, ...]:
    if subset == "full":
        return golden.items
    if subset == "ci":
        return golden.subset(set(ci_items))
    return golden.subset({part.strip() for part in subset.split(",") if part.strip()})


def _resolve_configs(
    names: Sequence[str],
    models: Sequence[str],
    think: bool | None,
    available: dict[str, BenchConfig],
) -> list[BenchConfig]:
    configs = []
    for name in names:
        if name not in available:
            raise BenchError(f"unknown configuration {name!r}; known: {sorted(available)}")
        configs.append(available[name])
    configs += [BenchConfig.single(model, think) for model in models]
    if not configs:
        raise BenchError("nothing to run: pass --configs and/or --models")
    return configs


async def _pulled_models(base_url: str) -> set[str]:
    async with httpx.AsyncClient(base_url=base_url, timeout=10) as client:
        response = await client.get("/api/tags")
        response.raise_for_status()
        return {model["name"] for model in response.json().get("models", [])}


def _cosine(a: Sequence[float], b: Sequence[float]) -> float:
    dot = sum(x * y for x, y in zip(a, b, strict=True))
    norm = math.sqrt(sum(x * x for x in a)) * math.sqrt(sum(y * y for y in b))
    return dot / norm if norm else 0.0


async def find_overlaps(
    examples: Sequence[str],
    items: Sequence[GoldenItem],
    embed: Callable[[str], Awaitable[list[float]]],
) -> list[str]:
    """Example questions that repeat (same normalized text) or paraphrase (cosine) a golden one."""
    golden_keys = {question_key(item.question): item.id for item in items}
    leaks = [
        f"{golden_keys[question_key(q)]} = «{q}» (same text)"
        for q in examples
        if question_key(q) in golden_keys
    ]
    if not examples:
        return leaks
    golden_vectors = [await embed(item.question) for item in items]
    for question in examples:
        if question_key(question) in golden_keys:
            continue
        vector = await embed(question)
        for item, golden_vector in zip(items, golden_vectors, strict=True):
            similarity = _cosine(vector, golden_vector)
            if similarity >= OVERLAP_COSINE:
                leaks.append(f"{item.id} ≈ «{question}» (cosine {similarity:.2f})")
    return leaks


async def check_leakage(
    sessions: async_sessionmaker[AsyncSession],
    embedder: Embedder,
    connection_key: str,
    items: Sequence[GoldenItem],
) -> list[str]:
    """Verified few-shot examples of the source that leak golden questions (ADR-0015)."""
    async with sessions() as session:
        examples = (
            await session.scalars(
                select(VerifiedExample.question).where(
                    VerifiedExample.connection_key == connection_key
                )
            )
        ).all()
    return await find_overlaps(list(examples), items, embedder.embed_query)


def _progress(total: int) -> Callable[[ItemOutcome], None]:
    done = {"n": 0, "ok": 0}

    def report(outcome: ItemOutcome) -> None:
        done["n"] += 1
        done["ok"] += int(outcome.correct)
        mark = "✓" if outcome.correct else "✗"
        seconds = outcome.latency_ms / 1000
        print(
            f"  [{done['n']:3d}/{total}] {mark} {outcome.item_id} {seconds:6.1f}s "
            f"{outcome.reason:18s} acc={done['ok'] / done['n']:.3f}",
            flush=True,
        )

    return report


def _load_checked(golden_dir: Path) -> tuple[GoldenSet, ExpectedResults]:
    golden = GoldenSet.load(golden_dir)
    expected = ExpectedResults.load(golden_dir)
    stale = expected.stale(golden)
    if stale:
        raise BenchError(f"golden answers are stale for {stale}: run `make bench-freeze`")
    if expected.dataset_version != DATASET_VERSION:
        raise BenchError(
            f"expected.json was frozen for dataset {expected.dataset_version}, "
            f"the demo is {DATASET_VERSION}: re-freeze"
        )
    return golden, expected


async def _run_config(
    config: BenchConfig,
    runtime: SourceRuntime,
    *,
    settings: Settings,
    items: Sequence[GoldenItem],
    expected: ExpectedResults,
    sessions: async_sessionmaker[AsyncSession],
    args: argparse.Namespace,
    subset: str,
) -> RunRecord:
    provider = OllamaProvider(
        str(settings.ollama.base_url),
        config.model,
        settings.ollama.embedding_model,
        timeout_s=settings.agent.llm_timeout_s,
        think=config.think,
    )

    async def make_context(events: EventSink, audit: AuditSink, memory: MemorySink) -> AgentContext:
        return runtime.agent_context(
            llm=provider,
            events=events,
            audit=audit,
            memory=memory,
            max_repairs=settings.agent.max_repairs,
            models=config.routing(),
        )

    print(f"== {config.name} ({', '.join(config.models)}): {len(items)} questions", flush=True)
    started = dt.datetime.now(dt.UTC)
    git_sha = args.git_sha or None
    run_id = await start_run(
        sessions, config, subset=subset, dataset_version=DATASET_VERSION, git_sha=git_sha
    )
    try:
        outcomes = await run_items(
            build_graph(), make_context, items, expected, on_item=_progress(len(items))
        )
    except BaseException as exc:
        await fail_run(sessions, run_id, f"{type(exc).__name__}: {exc}")
        raise
    summary = summarize(outcomes)
    await finish_run(sessions, run_id, outcomes, summary)
    return RunRecord(
        run_id=str(run_id),
        config=config,
        subset=subset,
        dataset_version=DATASET_VERSION,
        git_sha=git_sha,
        started_at=started,
        finished_at=dt.datetime.now(dt.UTC),
        summary=summary,
        outcomes=outcomes,
    )


async def run(args: argparse.Namespace, settings: Settings) -> int:
    golden, expected = _load_checked(args.golden)
    ci = load_ci(args.configs_file)
    configs = _resolve_configs(
        args.configs, args.models, args.think, load_configs(args.configs_file)
    )
    items = _select_items(golden, args.subset, ci.items)
    if args.limit:
        items = items[: args.limit]
    subset = args.subset if args.subset in ("full", "ci") else "custom"

    missing = sorted(
        {m for c in configs for m in c.models} - await _pulled_models(str(settings.ollama.base_url))
    )
    if missing:
        raise BenchError(f"models not pulled in Ollama: {missing}")

    app_engine = create_engine(settings.app_db, application_name="nexus-bench")
    demo_engine = create_engine(settings.demo_db, application_name="nexus-bench-reader")
    sessions = async_sessionmaker(app_engine, expire_on_commit=False)
    embedder = Embedder(
        OllamaProvider(
            str(settings.ollama.base_url),
            settings.ollama.llm_model,
            settings.ollama.embedding_model,
        ),
        profile_for(settings.ollama.embedding_model),
    )
    registry = ConnectionRegistry(
        settings=settings,
        sessions=sessions,
        store=PgDocumentStore(sessions),
        embedder=embedder,
        builtin=builtin_spec(settings),
        builtin_engine=demo_engine,
    )
    key = settings.agent.connection_key
    try:
        await registry.index(key)
        runtime = await registry.get(key)
        leaks = await check_leakage(sessions, embedder, key, items)
        if leaks and not args.allow_example_overlap:
            raise BenchError("verified examples overlap the golden set: " + "; ".join(leaks))
        for config in configs:
            record = await _run_config(
                config,
                runtime,
                settings=settings,
                items=items,
                expected=expected,
                sessions=sessions,
                args=args,
                subset=subset,
            )
            path = write_record(args.results, record)
            s = record.summary
            print(
                f"== {config.name}: accuracy {s.accuracy:.3f} ({s.correct}/{s.items}), "
                f"p50 {s.latency_p50_ms / 1000:.1f}s, p95 {s.latency_p95_ms / 1000:.1f}s -> {path}",
                flush=True,
            )
    finally:
        await registry.close()
        await demo_engine.dispose()
        await app_engine.dispose()
    return 0


# ---- report / check --------------------------------------------------------------------------


class CiGate:
    def __init__(self, config: str, items: Sequence[str], min_accuracy: float) -> None:
        self.config = config
        self.items = tuple(items)
        self.min_accuracy = min_accuracy


def load_ci(configs_file: Path) -> CiGate:
    raw = yaml.safe_load(configs_file.read_text(encoding="utf-8")) or {}
    ci = raw.get("ci") or {}
    return CiGate(
        str(ci.get("config", "")), list(ci.get("items", [])), float(ci.get("min_accuracy", 0))
    )


def report(args: argparse.Namespace) -> int:
    golden = GoldenSet.load(args.golden)
    records = read_records(args.results)
    args.out.write_text(render(records, golden, hardware=args.hardware), encoding="utf-8")
    latest = latest_by_config(records)
    chosen = select_default({n: r.summary for n, r in latest.items()}, eligible_configs(latest))
    print(f"wrote {args.out} ({len(records)} run records; selected: {chosen})")
    return 0


def check(args: argparse.Namespace) -> int:
    """CI gate: the newest CI-subset run must reach the calibrated accuracy."""
    ci = load_ci(args.configs_file)
    records = [r for r in read_records(args.results) if r.subset == "ci"]
    if not records:
        print("no CI-subset run record found", file=sys.stderr)
        return 2
    newest = max(records, key=lambda r: r.finished_at)
    accuracy = newest.summary.accuracy
    verdict = "PASS" if accuracy >= ci.min_accuracy else "FAIL"
    print(
        f"{verdict}: {newest.config.name} accuracy {accuracy:.3f} on {newest.summary.items} "
        f"questions (threshold {ci.min_accuracy:.3f})"
    )
    return 0 if verdict == "PASS" else 1


# ---- entry point -----------------------------------------------------------------------------


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="nexus-bench", description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    defaults = {"golden": Path("bench/golden"), "results": Path("bench/results")}

    p_freeze = sub.add_parser("freeze", help="execute the gold SQL and freeze expected.json")
    p_freeze.add_argument("--golden", type=Path, default=defaults["golden"])

    p_run = sub.add_parser("run", help="run configurations over the golden set")
    p_run.add_argument("--golden", type=Path, default=defaults["golden"])
    p_run.add_argument("--results", type=Path, default=defaults["results"])
    p_run.add_argument("--configs-file", type=Path, default=Path("bench/configs.yaml"))
    p_run.add_argument("--configs", nargs="*", default=[], help="named configurations")
    p_run.add_argument("--models", nargs="*", default=[], help="single-model configurations")
    p_run.add_argument(
        "--think",
        choices=("on", "off", "default"),
        default="off",
        help="reasoning toggle for --models (named configurations set their own)",
    )
    p_run.add_argument("--subset", default="full", help="full | ci | comma-separated ids")
    p_run.add_argument("--limit", type=int, default=0)
    p_run.add_argument("--git-sha", default="")
    p_run.add_argument("--allow-example-overlap", action="store_true")

    p_report = sub.add_parser("report", help="render docs/benchmark.md")
    p_report.add_argument("--golden", type=Path, default=defaults["golden"])
    p_report.add_argument("--results", type=Path, default=defaults["results"])
    p_report.add_argument("--out", type=Path, default=Path("docs/benchmark.md"))
    p_report.add_argument("--hardware", default="not recorded")

    p_check = sub.add_parser("check", help="CI gate on the newest CI-subset run")
    p_check.add_argument("--results", type=Path, default=defaults["results"])
    p_check.add_argument("--configs-file", type=Path, default=Path("bench/configs.yaml"))
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        if args.command == "report":
            return report(args)
        if args.command == "check":
            return check(args)
        settings = get_settings()
        configure_logging("WARNING", json=False)
        if args.command == "freeze":
            return asyncio.run(freeze(args.golden, settings))
        args.think = {"on": True, "off": False, "default": None}[args.think]
        return asyncio.run(run(args, settings))
    except BenchError as exc:
        print(f"nexus-bench: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
