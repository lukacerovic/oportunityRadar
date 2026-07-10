"""Collector contract (doc 03 §1). Collectors record; they never interpret.

A collector fetches from one source and returns ``RawEventDraft`` rows. The framework
(``runner.py``) owns dedupe, persistence, health rows, and retries — a collector that
contains an ``if`` about *meaning* is wrong.
"""

from __future__ import annotations

import time
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol

from pydantic import BaseModel, Field


@dataclass(frozen=True)
class Window:
    """Half-open collection window ``[since, until)``, timezone-aware UTC."""

    since: datetime
    until: datetime

    @classmethod
    def last(cls, days: float, *, now: datetime | None = None) -> Window:
        until = now or datetime.now(UTC)
        return cls(since=until - timedelta(days=days), until=until)


class RawEventDraft(BaseModel):
    """A single uninterpreted observation, before it becomes a ``raw_events`` row."""

    source: str
    source_event_uid: str
    event_type: str
    occurred_at: datetime
    payload: dict[str, Any] = Field(default_factory=dict)
    origin: str = "live"

    @staticmethod
    def snapshot_uid(native_id: str, occurred_at: datetime) -> str:
        """Stable per-target-per-day uid for ``*_snapshot`` events (doc 03 §1, A-11: UTC date)."""
        return f"{native_id}:{occurred_at.astimezone(UTC).date().isoformat()}"


class TrackTarget(BaseModel):
    """A known entity to deep-poll (doc 03 DR-03.3). Populated once identity exists (Stage 2)."""

    entity_id: int
    source: str
    native_id: str  # 'owner/repo', a package name, an 'org/model', ...


class BaseCollector(Protocol):
    source: str

    def discover(self, window: Window) -> list[RawEventDraft]:
        """Find new candidate entities in the window (broad, shallow)."""
        ...

    def track(self, targets: list[TrackTarget], window: Window) -> list[RawEventDraft]:
        """Deep-poll entities we already know (narrow, deep)."""
        ...


class RateLimiter:
    """Minimum-interval limiter, honored even in backfills (doc 03 §4.1).

    ``min_interval_s=0`` disables waiting (used in tests). Uses a monotonic clock and an
    injectable ``sleep`` so tests never actually block.
    """

    def __init__(
        self, min_interval_s: float, *, sleep: Any = time.sleep, clock: Any = time.monotonic
    ):
        self.min_interval_s = min_interval_s
        self._sleep = sleep
        self._clock = clock
        self._last: float | None = None

    def wait(self) -> None:
        if self.min_interval_s <= 0:
            return
        now = self._clock()
        if self._last is not None:
            elapsed = now - self._last
            if elapsed < self.min_interval_s:
                self._sleep(self.min_interval_s - elapsed)
        self._last = self._clock()
