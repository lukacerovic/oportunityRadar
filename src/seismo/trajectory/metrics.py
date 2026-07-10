"""Metric snapshots (doc 06 §1) — the ``seismo snapshot`` job.

Reads the entity-attached event stream visible at ``as_of`` and writes one value per
``(entity, metric, day)`` into ``entity_metrics_daily``. ``day`` is the UTC calendar date of
``occurred_at`` (doc 13 A-11). Every read is as-of correct: events resolve to their canonical
entity via :func:`canonical_entity_id` at ``as_of``, so a hindcast never sees a future merge.

Three metric kinds, each with different gap semantics (doc 06 §1):

* **counter** (``gh_stars``/``gh_forks``) — cumulative snapshot level; forward-filled up to 3 days
  across collector hiccups (a counter that isn't re-observed hasn't dropped to zero).
* **level** (``hf_downloads_30d``/``pypi_downloads_7d``) — a rolling level the *source* already
  windows; **never diffed as a counter and never forward-filled** (doc 03 §2.4 / HANDOFF gotcha).
* **rolling** (``hn_points_7d``) — we sum a discovery-event field over a trailing window ourselves.

``evidence_breadth`` is derived: the count of distinct evidence *types* with any activity in the
trailing 30 days (0–5). It feeds the ``breakout`` breadth gate (doc 06 §4) and is not a source
metric.
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from decimal import Decimal
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from seismo.db import canonical_entity_id

BREADTH_METRIC = "evidence_breadth"
BREADTH_WINDOW_DAYS = 30


@dataclass(frozen=True)
class MetricSpec:
    """One canonical metric (doc 06 §1). ``evidence_type`` is the 5-types taxonomy (idea-spec §5);
    ``composite`` marks the usage/participation metrics that feed the velocity percentile —
    attention is excluded from the composite (idea-spec principle 3) but still counts to breadth."""

    name: str
    kind: str  # counter | level | rolling
    evidence_type: str  # attention | participation | usage
    source: str
    event_type: str
    field: str
    composite: bool
    window_days: int = 0  # rolling only
    forward_fill_days: int = 0  # counters only


# v1 = 3 live evidence types (attention/participation/usage); pricing/jobs land later (doc 13 A-5).
# hf/pypi specs are declared now so the snapshot job is complete the day those collectors ship.
METRIC_SPECS: tuple[MetricSpec, ...] = (
    MetricSpec(
        "gh_stars",
        "counter",
        "participation",
        "github",
        "repo_snapshot",
        "stars",
        composite=True,
        forward_fill_days=3,
    ),
    MetricSpec(
        "gh_forks",
        "counter",
        "participation",
        "github",
        "repo_snapshot",
        "forks",
        composite=True,
        forward_fill_days=3,
    ),
    # GH Archive backfill reconstructs stars as individual ``repo_star`` (WatchEvent) events; the
    # cumulative count per day *is* the star series for a historical window. It feeds the same
    # ``gh_stars`` metric so velocity is computed identically whether stars came from a live
    # ``repo_snapshot`` level or backfilled counts. (Seam caveat: an entity that has both — live
    # snapshots after a historical backfill — sees an absolute-vs-window-relative jump at the
    # boundary; a hindcast at a past as_of only sees backfill, so H1 is clean.)
    MetricSpec(
        "gh_stars", "cumulative", "participation", "github", "repo_star", "", composite=True
    ),
    MetricSpec(
        "hf_downloads_30d", "level", "usage", "hf", "model_snapshot", "downloads", composite=True
    ),
    MetricSpec(
        "pypi_downloads_7d",
        "level",
        "usage",
        "pypi",
        "pypi_snapshot",
        "downloads_7d",
        composite=True,
    ),
    MetricSpec(
        "hn_points_7d",
        "rolling",
        "attention",
        "hn",
        "story",
        "points",
        composite=False,
        window_days=7,
    ),
)

COMPOSITE_METRICS: frozenset[str] = frozenset(s.name for s in METRIC_SPECS if s.composite)
EVIDENCE_TYPES: frozenset[str] = frozenset(s.evidence_type for s in METRIC_SPECS)


@dataclass
class _Ev:
    """One attached event, resolved to its canonical entity at ``as_of``."""

    entity_id: int
    day: date
    source: str
    event_type: str
    payload: dict[str, Any]


@dataclass
class SnapshotStats:
    events_read: int = 0
    entities: int = 0
    rows_written: int = 0
    per_metric: dict[str, int] = field(default_factory=dict)

    def as_note(self) -> str:
        metrics = " ".join(f"{k}={v}" for k, v in sorted(self.per_metric.items()))
        return (
            f"events={self.events_read} entities={self.entities} "
            f"rows={self.rows_written} [{metrics}]"
        )


def run_snapshot(session: Session, as_of: datetime) -> SnapshotStats:
    """Rebuild ``entity_metrics_daily`` for every metric using events visible at ``as_of``.

    Deterministic and idempotent: it recomputes each ``(entity, metric, day)`` from raw events and
    upserts, so re-running for the same ``as_of`` is a no-op. Rebuilding (rather than appending) is
    what keeps the metric table a pure function of events ≤ ``as_of`` (doc 06 §5)."""
    streams = _entity_streams(session, as_of)
    stats = SnapshotStats(entities=len(streams))
    stats.events_read = sum(len(v) for v in streams.values())

    rows: list[tuple[int, str, date, Decimal]] = []
    for spec in METRIC_SPECS:
        if spec.kind == "rolling":
            rows.extend(_rolling_rows(streams, spec, as_of))
        elif spec.kind == "cumulative":
            rows.extend(_cumulative_rows(streams, spec, as_of))
        else:
            rows.extend(_point_rows(streams, spec, as_of))
    rows.extend(_breadth_rows(streams, as_of))

    # Dedup on the (entity, metric, day) key, last write wins — two sources can feed one metric
    # (e.g. gh_stars from repo_snapshot *and* backfilled repo_star), and a single upsert batch may
    # not touch the same conflict target twice.
    deduped: dict[tuple[int, str, date], Decimal] = {}
    for entity_id, metric, day, value in rows:
        deduped[(entity_id, metric, day)] = value
    final = [(e, m, d, v) for (e, m, d), v in deduped.items()]
    for _e, metric, _d, _v in final:
        stats.per_metric[metric] = stats.per_metric.get(metric, 0) + 1
    stats.rows_written = _upsert_metrics(session, final)
    return stats


def _entity_streams(session: Session, as_of: datetime) -> dict[int, list[_Ev]]:
    """Attached events (rule='attach') visible at ``as_of``, grouped by canonical entity.

    Only attachment links carry an event; merge/audit links (linked_entity_id) don't. Canonical
    resolution folds a merged loser's events onto the survivor as the graph stood at ``as_of``."""
    sql = text(
        """
        SELECT l.entity_id AS entity_id, r.source AS source, r.event_type AS event_type,
               r.occurred_at AS occurred_at, r.payload AS payload
        FROM entity_links l
        JOIN raw_events r ON r.id = l.raw_event_id
        WHERE l.rule = 'attach' AND r.occurred_at <= :as_of
        ORDER BY r.occurred_at
        """
    )
    canonical: dict[int, int] = {}
    streams: dict[int, list[_Ev]] = defaultdict(list)
    for row in session.execute(sql, {"as_of": as_of}).mappings():
        raw_id = row["entity_id"]
        if raw_id not in canonical:
            canonical[raw_id] = canonical_entity_id(session, raw_id, as_of)
        occurred: datetime = row["occurred_at"]
        streams[canonical[raw_id]].append(
            _Ev(
                entity_id=canonical[raw_id],
                day=occurred.date(),
                source=row["source"],
                event_type=row["event_type"],
                payload=row["payload"] or {},
            )
        )
    return streams


def _point_rows(
    streams: dict[int, list[_Ev]], spec: MetricSpec, as_of: datetime
) -> list[tuple[int, str, date, Decimal]]:
    """Counter/level: take each day's observed value (last snapshot of the day wins). Counters
    forward-fill up to ``forward_fill_days`` between observations; levels never fill (doc 06 §1)."""
    as_of_day = as_of.date()
    out: list[tuple[int, str, date, Decimal]] = []
    for entity_id, evs in streams.items():
        by_day: dict[date, Decimal] = {}
        for ev in evs:
            if ev.source != spec.source or ev.event_type != spec.event_type:
                continue
            raw = ev.payload.get(spec.field)
            if raw is None:
                continue
            by_day[ev.day] = Decimal(str(raw))  # last write per day wins (evs are time-ordered)
        if not by_day:
            continue
        if spec.forward_fill_days > 0:
            by_day = _forward_fill(by_day, spec.forward_fill_days, as_of_day)
        for day, value in by_day.items():
            out.append((entity_id, spec.name, day, value))
    return out


def _forward_fill(
    observed: dict[date, Decimal], max_days: int, as_of_day: date
) -> dict[date, Decimal]:
    """Carry a counter forward across gaps up to ``max_days``, never past ``as_of_day``. A gap wider
    than ``max_days`` leaves a hole — we don't invent a level we never saw."""
    filled = dict(observed)
    days = sorted(observed)
    for i, day in enumerate(days):
        stop = days[i + 1] if i + 1 < len(days) else as_of_day + timedelta(days=1)
        value = observed[day]
        for step in range(1, max_days + 1):
            nxt = day + timedelta(days=step)
            if nxt >= stop or nxt > as_of_day:
                break
            filled.setdefault(nxt, value)
    return filled


def _cumulative_rows(
    streams: dict[int, list[_Ev]], spec: MetricSpec, as_of: datetime
) -> list[tuple[int, str, date, Decimal]]:
    """Cumulative event count as a daily level (each matching event = +1). Emits a monotonic step
    per day the count changes — the reconstructed star series from GH Archive ``repo_star`` events.
    The window-relative offset is irrelevant to velocity (a 7-day change), which is the point."""
    as_of_day = as_of.date()
    out: list[tuple[int, str, date, Decimal]] = []
    for entity_id, evs in streams.items():
        star_days = sorted(
            ev.day
            for ev in evs
            if ev.source == spec.source and ev.event_type == spec.event_type and ev.day <= as_of_day
        )
        if not star_days:
            continue
        per_day: dict[date, int] = defaultdict(int)
        for d in star_days:
            per_day[d] += 1
        running = 0
        for day in sorted(per_day):
            running += per_day[day]
            out.append((entity_id, spec.name, day, Decimal(running)))
    return out


def _rolling_rows(
    streams: dict[int, list[_Ev]], spec: MetricSpec, as_of: datetime
) -> list[tuple[int, str, date, Decimal]]:
    """Rolling sum of a discovery-event field over a trailing ``window_days`` window. Emitted only
    for days on which the value is nonzero (the window straddles at least one event)."""
    as_of_day = as_of.date()
    win = spec.window_days
    out: list[tuple[int, str, date, Decimal]] = []
    for entity_id, evs in streams.items():
        contribs = [
            (ev.day, Decimal(str(ev.payload.get(spec.field) or 0)))
            for ev in evs
            if ev.source == spec.source and ev.event_type == spec.event_type
        ]
        if not contribs:
            continue
        # A day's window (D-win, D] covers events with event_day in [D-win+1, D]; i.e. an event on
        # E contributes to days E..E+win-1. Emit each such day once, capped at as_of.
        candidate_days: set[date] = set()
        for event_day, _ in contribs:
            for step in range(win):
                d = event_day + timedelta(days=step)
                if d <= as_of_day:
                    candidate_days.add(d)
        for day in candidate_days:
            lo = day - timedelta(days=win)
            total = sum((v for (ed, v) in contribs if lo < ed <= day), Decimal(0))
            if total > 0:
                out.append((entity_id, spec.name, day, total))
    return out


def _breadth_rows(
    streams: dict[int, list[_Ev]], as_of: datetime
) -> list[tuple[int, str, date, Decimal]]:
    """``evidence_breadth`` = distinct evidence types active in the trailing 30d. Corroboration
    breadth is the core signal (idea-spec §5), so this is a first-class daily metric."""
    as_of_day = as_of.date()
    source_type = {s.source: s.evidence_type for s in METRIC_SPECS}
    out: list[tuple[int, str, date, Decimal]] = []
    for entity_id, evs in streams.items():
        typed = [(ev.day, source_type[ev.source]) for ev in evs if ev.source in source_type]
        if not typed:
            continue
        candidate_days: set[date] = set()
        for event_day, _ in typed:
            for step in range(BREADTH_WINDOW_DAYS):
                d = event_day + timedelta(days=step)
                if d <= as_of_day:
                    candidate_days.add(d)
        for day in candidate_days:
            lo = day - timedelta(days=BREADTH_WINDOW_DAYS)
            active = {etype for (ed, etype) in typed if lo < ed <= day}
            if active:
                out.append((entity_id, BREADTH_METRIC, day, Decimal(len(active))))
    return out


def _upsert_metrics(session: Session, rows: list[tuple[int, str, date, Decimal]]) -> int:
    """Idempotent upsert into ``entity_metrics_daily``. Returns the number of rows written."""
    if not rows:
        return 0
    stmt = text(
        """
        INSERT INTO entity_metrics_daily (entity_id, metric, day, value)
        VALUES (:entity_id, :metric, :day, :value)
        ON CONFLICT (entity_id, metric, day) DO UPDATE SET value = EXCLUDED.value
        """
    )
    session.execute(
        stmt,
        [{"entity_id": e, "metric": m, "day": d, "value": v} for (e, m, d, v) in rows],
    )
    return len(rows)
