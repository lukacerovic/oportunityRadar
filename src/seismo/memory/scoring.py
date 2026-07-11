"""Brief forward-scoring (doc 09 §2) — the human half of the calibration loop, with A-7 auto-assist.

Every published brief is revisited a quarter later: did the exposure materialize, did a falsifier
trip, was the counter-mechanism the better story (idea-spec §9)? That judgment is a **ritual with a
UI, not an automation** (DR-09.2) — grading the system with the system would be worthless. What this
module automates is the *assembly*: it gathers the brief, its observables, and the since-publication
metric history into one packet, and — per A-7 — **auto-evaluates the ``source='system'``
observables** by comparing the metric's actual movement against the direction the thesis predicted.
The operator then judges the ``manual`` falsifiers and records the verdict via :func:`record_score`.

Auto-evaluation is advisory: it never writes a score on its own. It turns "go read the charts" into
"here is what the measurable falsifiers already say," so the quarterly ritual is minutes, not hours.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

# How much a system metric must move (fractionally) before we call it a direction, not noise.
_FLAT_BAND = 0.05

# Horizon → the days that must elapse before a "didn't happen yet" reads as evidence, not too-early.
_HORIZON_DAYS = {"quarters": 90, "1-2y": 365, "3y+": 1095}

MATERIALIZED_VALUES = ("yes", "partial", "no", "too_early")


@dataclass
class ObservableEval:
    """One observable's auto-evaluation (A-7). ``manual`` observables are ``operator_judgment``."""

    statement: str
    source: str  # system | manual
    system_metric: str | None
    direction_if_thesis_holds: str  # up | down | flat
    status: str  # on_track | counter | flat | too_early | unmeasurable | operator_judgment
    detail: str


@dataclass
class ScorePacket:
    """Everything the scoring screen (doc 09 §2) needs to grade one brief in a single view."""

    brief_id: int
    entity_id: int
    entity_name: str
    version: int
    published_at: datetime | None
    horizon: str | None
    days_elapsed: int
    summary: str | None
    counter_mechanism: str | None
    exposures: list[dict[str, Any]]
    observable_evals: list[ObservableEval]
    metric_history: dict[str, list[tuple[str, float]]]  # metric → [(day_iso, value)] since publish
    existing_score: dict[str, Any] | None
    auto_summary: str  # one-line roll-up of the system observables' verdicts

    def as_note(self) -> str:
        return (
            f"brief={self.brief_id} entity={self.entity_name} elapsed={self.days_elapsed}d "
            f"— {self.auto_summary}"
        )


def assemble_score_packet(
    session: Session, brief_id: int, *, now: datetime | None = None
) -> ScorePacket:
    """Gather a brief + observables + since-publication metric history and auto-evaluate its
    system observables (A-7). Pure read; writes nothing (scoring itself is :func:`record_score`)."""
    now = now or datetime.now(UTC)
    row = (
        session.execute(
            text(
                "SELECT b.entity_id, b.version, b.status, b.brief, b.as_of, b.reviewed_at,"
                " b.created_at, e.canonical_name"
                " FROM impact_briefs b JOIN entities e ON e.id = b.entity_id WHERE b.id = :id"
            ),
            {"id": brief_id},
        )
        .mappings()
        .first()
    )
    if row is None:
        raise ValueError(f"no impact_brief with id {brief_id}")

    brief = row["brief"] or {}
    # Anchor the "since publication" window at review time if published, else at draft creation.
    published_at = row["reviewed_at"] or row["created_at"]
    days_elapsed = (now - published_at).days if published_at else 0
    horizon = brief.get("horizon")

    exposures = brief.get("exposures") or []
    observables = brief.get("observables") or []
    metrics_wanted = {
        o.get("system_metric")
        for o in observables
        if o.get("source") == "system" and o.get("system_metric")
    }
    history = _metric_history(session, row["entity_id"], published_at, now, metrics_wanted)

    evals = [_evaluate_observable(o, history, days_elapsed, horizon) for o in observables]
    auto = _roll_up(evals)

    existing = (
        session.execute(
            text(
                "SELECT scored_at, materialized, falsifier_tripped, notes"
                " FROM brief_scores WHERE brief_id = :id"
            ),
            {"id": brief_id},
        )
        .mappings()
        .first()
    )

    return ScorePacket(
        brief_id=brief_id,
        entity_id=row["entity_id"],
        entity_name=row["canonical_name"],
        version=row["version"],
        published_at=published_at,
        horizon=horizon,
        days_elapsed=days_elapsed,
        summary=brief.get("summary"),
        counter_mechanism=brief.get("counter_mechanism"),
        exposures=exposures,
        observable_evals=evals,
        metric_history=history,
        existing_score=dict(existing) if existing else None,
        auto_summary=auto,
    )


def _evaluate_observable(
    obs: dict[str, Any],
    history: dict[str, list[tuple[str, float]]],
    days_elapsed: int,
    horizon: str | None,
) -> ObservableEval:
    source = obs.get("source", "manual")
    stmt = obs.get("statement", "")
    direction = obs.get("direction_if_thesis_holds", "flat")
    metric = obs.get("system_metric")

    base = ObservableEval(
        statement=stmt,
        source=source,
        system_metric=metric,
        direction_if_thesis_holds=direction,
        status="operator_judgment",
        detail="Manual observable — record your read below." if source == "manual" else "",
    )
    if source != "system":
        return base
    if not metric or metric not in history or len(history[metric]) < 2:
        base.status = "unmeasurable"
        base.detail = f"No pipeline series for metric {metric!r} since publication."
        return base

    series = history[metric]
    first_v, last_v = series[0][1], series[-1][1]
    change = _pct_change(first_v, last_v)
    moved = "up" if change > _FLAT_BAND else ("down" if change < -_FLAT_BAND else "flat")

    # Not enough time has passed to hold the observable to account.
    horizon_days = _HORIZON_DAYS.get(horizon or "", 90)
    if moved == "flat" and days_elapsed < horizon_days:
        base.status = "too_early"
        base.detail = (
            f"{metric} ~flat ({change:+.0%}); {days_elapsed}d of a {horizon_days}d horizon elapsed."
        )
        return base

    if moved == direction:
        base.status = "on_track"
    elif moved == "flat":
        base.status = "flat"
    else:
        base.status = "counter"
    base.detail = f"{metric} {first_v:g}→{last_v:g} ({change:+.0%}); thesis expected {direction}."
    return base


def _roll_up(evals: list[ObservableEval]) -> str:
    system = [e for e in evals if e.source == "system"]
    if not system:
        return "no system-measurable observables — manual scoring only"
    from collections import Counter

    counts = Counter(e.status for e in system)
    parts = [f"{n}×{status}" for status, n in counts.most_common()]
    return "system observables: " + ", ".join(parts)


def record_score(
    session: Session,
    brief_id: int,
    *,
    materialized: str,
    falsifier_tripped: bool = False,
    falsifier_observable: str | None = None,
    verdict: str | None = None,
    counter_was_better: bool = False,
) -> None:
    """Record the operator's quarterly verdict into ``brief_scores`` (DR-09.2). Re-scoring updates
    the row. The which-observable + verdict + counter-mechanism flag ride in ``notes`` as JSON so no
    schema change is needed on the migration-0001 table."""
    if materialized not in MATERIALIZED_VALUES:
        raise ValueError(f"materialized must be one of {MATERIALIZED_VALUES}, got {materialized!r}")
    exists = session.execute(
        text("SELECT 1 FROM impact_briefs WHERE id = :id"), {"id": brief_id}
    ).first()
    if exists is None:
        raise ValueError(f"no impact_brief with id {brief_id}")
    notes = json.dumps(
        {
            "verdict": verdict,
            "counter_was_better": counter_was_better,
            "falsifier_observable": falsifier_observable,
        }
    )
    session.execute(
        text(
            """
            INSERT INTO brief_scores (brief_id, scored_at, materialized, falsifier_tripped, notes)
            VALUES (:id, now(), :m, :ft, :notes)
            ON CONFLICT (brief_id) DO UPDATE
              SET scored_at = now(), materialized = EXCLUDED.materialized,
                  falsifier_tripped = EXCLUDED.falsifier_tripped, notes = EXCLUDED.notes
            """
        ),
        {"id": brief_id, "m": materialized, "ft": falsifier_tripped, "notes": notes},
    )


def _metric_history(
    session: Session,
    entity_id: int,
    since: datetime | None,
    now: datetime,
    metrics: set[str],
) -> dict[str, list[tuple[str, float]]]:
    if not metrics or since is None:
        return {}
    rows = session.execute(
        text(
            """
            SELECT metric, day, value FROM entity_metrics_daily
            WHERE entity_id = :e AND metric = ANY(:metrics)
              AND day >= :since AND day <= :now ORDER BY metric, day
            """
        ),
        {"e": entity_id, "metrics": list(metrics), "since": since.date(), "now": now.date()},
    ).all()
    out: dict[str, list[tuple[str, float]]] = {}
    for metric, day, value in rows:
        out.setdefault(metric, []).append((day.isoformat(), float(value)))
    return out


def _pct_change(first: float, last: float) -> float:
    if first == 0:
        return 0.0 if last == 0 else 1.0
    return (last - first) / abs(first)
