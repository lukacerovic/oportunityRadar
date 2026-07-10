"""Collector framework responsibilities (doc 03 §1): dedupe-insert, health rows, failure
isolation. Collectors supply drafts; the runner owns everything durable.

Idempotence is the contract: persistence uses ``ON CONFLICT (source, source_event_uid)
DO NOTHING``, so re-running a window inserts zero duplicates (Stage 1 exit criterion).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from seismo.collectors.base import BaseCollector, RawEventDraft, TrackTarget, Window
from seismo.db import session_scope
from seismo.models import CollectorRun, RawEvent


@dataclass
class RunResult:
    source: str
    mode: str
    ok: bool
    events_new: int
    error: str | None = None


def persist_drafts(session: Session, drafts: list[RawEventDraft]) -> int:
    """Insert drafts, skipping conflicts on the natural key. Returns rows actually inserted."""
    if not drafts:
        return 0
    rows = [d.model_dump() for d in drafts]
    stmt = (
        pg_insert(RawEvent)
        .values(rows)
        .on_conflict_do_nothing(index_elements=["source", "source_event_uid"])
        .returning(RawEvent.id)
    )
    # RETURNING yields a row only for genuinely-inserted rows (conflicts return nothing),
    # so this is an exact insert count regardless of driver rowcount quirks.
    return len(session.execute(stmt).fetchall())


def _execute(
    session: Session,
    collector: BaseCollector,
    mode: str,
    window: Window,
    targets: list[TrackTarget] | None,
) -> RunResult:
    """Run one collector against a session. Never raises — failures are isolated (doc 03 §4.3)."""
    started = datetime.now(UTC)
    try:
        if mode == "discover":
            drafts = collector.discover(window)
        elif mode == "track":
            drafts = collector.track(targets or [], window)
        else:
            raise ValueError(f"unknown mode {mode!r}")
        new = persist_drafts(session, drafts)
        session.add(
            CollectorRun(
                source=collector.source,
                started_at=started,
                finished_at=datetime.now(UTC),
                ok=True,
                events_new=new,
            )
        )
        return RunResult(collector.source, mode, ok=True, events_new=new)
    except Exception as exc:  # isolate: record and continue with other sources
        error = f"{type(exc).__name__}: {exc}"[:1000]
        session.add(
            CollectorRun(
                source=collector.source,
                started_at=started,
                finished_at=datetime.now(UTC),
                ok=False,
                events_new=0,
                error=error,
            )
        )
        return RunResult(collector.source, mode, ok=False, events_new=0, error=error)


def run_collector(
    collector: BaseCollector,
    window: Window,
    *,
    mode: str = "discover",
    targets: list[TrackTarget] | None = None,
    session: Session | None = None,
) -> RunResult:
    """Run a collector and persist results + a health row.

    If ``session`` is provided the caller owns the transaction (used by tests, which roll
    back); otherwise a fresh committing ``session_scope`` is used.
    """
    if session is not None:
        return _execute(session, collector, mode, window, targets)
    with session_scope() as own:
        return _execute(own, collector, mode, window, targets)
