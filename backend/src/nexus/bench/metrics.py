"""Aggregate benchmark metrics and the default-model selection rule (ADR-0003 §4, ADR-0015)."""

from __future__ import annotations

import math
from collections import defaultdict
from collections.abc import Collection, Sequence

from pydantic import BaseModel

from nexus.bench.golden import Difficulty
from nexus.bench.runner import ItemOutcome

# The project's reference conversation (the `make e2e-agent` acceptance test): the reference
# question and its follow-up. A configuration that cannot answer both is not eligible.
REFERENCE_ITEMS = ("h001", "h031")
SELECTION_MARGIN = (
    0.02  # configurations within 2 points of the best accuracy compete on p95 latency
)


class DifficultyScore(BaseModel):
    items: int
    correct: int
    accuracy: float


class Summary(BaseModel):
    items: int
    correct: int
    accuracy: float
    by_difficulty: dict[str, DifficultyScore]
    latency_p50_ms: float
    latency_p95_ms: float
    error_rate: float
    first_attempt_rate: float
    recovery_rate: float | None
    tokens_per_question: float
    grounding_fallback_rate: float | None
    recall_at_5: float | None
    context_complete_rate: float | None
    node_latency_ms: dict[str, float]
    reasons: dict[str, int]


def percentile(values: Sequence[float], q: float) -> float:
    """Nearest-rank percentile (no interpolation; stable on small samples)."""
    if not values:
        return 0.0
    ordered = sorted(values)
    rank = max(1, math.ceil(q / 100 * len(ordered)))
    return float(ordered[rank - 1])


def _mean(values: Sequence[float]) -> float | None:
    return round(sum(values) / len(values), 4) if values else None


def summarize(outcomes: Sequence[ItemOutcome]) -> Summary:
    n = len(outcomes)
    correct = sum(o.correct for o in outcomes)
    by_difficulty: dict[str, DifficultyScore] = {}
    for difficulty in Difficulty:
        group = [o for o in outcomes if o.difficulty == difficulty.value]
        if group:
            hits = sum(o.correct for o in group)
            by_difficulty[difficulty.value] = DifficultyScore(
                items=len(group), correct=hits, accuracy=round(hits / len(group), 4)
            )
    latencies = [o.latency_ms for o in outcomes]
    answering = [o for o in outcomes if o.sql_attempts > 0]
    repaired = [o for o in outcomes if o.repairs > 0]
    explained = [o for o in outcomes if o.explanation_fallback is not None]
    recalls = [o.recall_at_5 for o in outcomes if o.recall_at_5 is not None]
    complete = [o.context_complete for o in outcomes if o.context_complete is not None]
    per_node: defaultdict[str, list[float]] = defaultdict(list)
    for outcome in outcomes:
        totals: defaultdict[str, float] = defaultdict(float)
        for node in outcome.nodes:
            duration = node.get("duration_ms")
            if isinstance(duration, int | float):
                totals[str(node.get("node"))] += float(duration)
        for name, total in totals.items():
            per_node[name].append(total)
    reasons: defaultdict[str, int] = defaultdict(int)
    for outcome in outcomes:
        if not outcome.correct:
            reasons[outcome.reason] += 1
    return Summary(
        items=n,
        correct=correct,
        accuracy=round(correct / n, 4) if n else 0.0,
        by_difficulty=by_difficulty,
        latency_p50_ms=round(percentile(latencies, 50), 1),
        latency_p95_ms=round(percentile(latencies, 95), 1),
        error_rate=round(sum(o.status in ("error", "failed") for o in outcomes) / n, 4)
        if n
        else 0.0,
        first_attempt_rate=(
            round(sum(o.first_attempt_ok for o in answering) / len(answering), 4)
            if answering
            else 0.0
        ),
        recovery_rate=round(sum(o.correct for o in repaired) / len(repaired), 4)
        if repaired
        else None,
        tokens_per_question=round(
            sum(o.prompt_tokens + o.completion_tokens for o in outcomes) / n, 1
        )
        if n
        else 0.0,
        grounding_fallback_rate=(
            round(sum(bool(o.explanation_fallback) for o in explained) / len(explained), 4)
            if explained
            else None
        ),
        recall_at_5=_mean(recalls),
        context_complete_rate=_mean([1.0 if c else 0.0 for c in complete]),
        node_latency_ms={name: round(sum(v) / len(v), 1) for name, v in sorted(per_node.items())},
        reasons=dict(sorted(reasons.items(), key=lambda kv: -kv[1])),
    )


def is_eligible(correct_items: Collection[str]) -> bool:
    """A default must answer the reference question(s) (the Phase 2/4 acceptance test, ADR-0022)."""
    return all(item in correct_items for item in REFERENCE_ITEMS)


def select_default(
    summaries: dict[str, Summary], eligible: Collection[str] | None = None
) -> str | None:
    """Among eligible configurations: highest accuracy; within 2 points of it, the lowest p95."""
    if eligible is not None:
        summaries = {name: s for name, s in summaries.items() if name in eligible}
    if not summaries:
        return None
    best = max(s.accuracy for s in summaries.values())
    contenders = {
        name: s for name, s in summaries.items() if s.accuracy >= best - SELECTION_MARGIN - 1e-9
    }
    return min(
        contenders, key=lambda name: (contenders[name].latency_p95_ms, -contenders[name].accuracy)
    )
