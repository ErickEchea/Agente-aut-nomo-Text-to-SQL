"""In-process token-bucket rate limiter (ADR-0011). Single-replica by design; see PROGRESS.md."""

from __future__ import annotations

import math
import time
from collections.abc import Callable
from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class RateDecision:
    allowed: bool
    limit: int
    remaining: int
    retry_after_s: int
    reset_s: int


@dataclass(slots=True)
class _Bucket:
    tokens: float
    updated: float


class TokenBucketLimiter:
    """``per_minute`` requests per minute per key, with a burst of the same size."""

    def __init__(self, clock: Callable[[], float] = time.monotonic, max_keys: int = 50_000) -> None:
        self._clock = clock
        self._buckets: dict[str, _Bucket] = {}
        self._max_keys = max_keys

    def hit(self, key: str, per_minute: int) -> RateDecision:
        now = self._clock()
        rate = per_minute / 60.0
        bucket = self._buckets.get(key)
        if bucket is None:
            if len(self._buckets) >= self._max_keys:
                self._evict(now)
            bucket = self._buckets[key] = _Bucket(tokens=float(per_minute), updated=now)
        else:
            bucket.tokens = min(per_minute, bucket.tokens + (now - bucket.updated) * rate)
            bucket.updated = now
        reset = math.ceil((per_minute - bucket.tokens) / rate) if rate else 0
        if bucket.tokens >= 1.0:
            bucket.tokens -= 1.0
            return RateDecision(True, per_minute, int(bucket.tokens), 0, reset)
        retry_after = math.ceil((1.0 - bucket.tokens) / rate)
        return RateDecision(False, per_minute, 0, retry_after, reset)

    def _evict(self, now: float) -> None:
        """Drop buckets idle for over a minute (fully refilled: no state worth keeping).

        If none qualify, drop the oldest 10 % so memory stays bounded under a key-flooding attack.
        """
        stale = [k for k, b in self._buckets.items() if now - b.updated > 60]
        if not stale:
            by_age = sorted(self._buckets, key=lambda k: self._buckets[k].updated)
            stale = by_age[: max(1, len(by_age) // 10)]
        for key in stale:
            self._buckets.pop(key, None)
