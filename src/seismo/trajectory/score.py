"""``seismo score`` orchestrator (doc 06) — ladder promotions → velocity percentiles → momentum.

Deterministic and as-of pure (doc 06 §5): given ``as_of`` it reads only events/metrics ≤ ``as_of``
and the entity graph as it stood then, so a re-run for the same date is byte-identical. It writes,
for every tracked entity, one ``momentum_states`` row per day from the entity's first evidence to
``as_of`` (upsert), giving an immediately queryable state history for sparklines. A later run at a
larger ``as_of`` refines recent history — expected of a daily heartbeat, and still pure per date.

Order matters: ladder runs first so ``promo_30d`` (a momentum input) reflects today's promotions.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date, datetime

from sqlalchemy import text
from sqlalchemy.orm import Session

from seismo.db import canonical_entity_id
from seismo.trajectory import velocity as velocity_mod
from seismo.trajectory.ladder import LadderStats, run_ladder
from seismo.trajectory.states import replay


@dataclass
class ScoreStats:
    entities: int = 0
    state_rows: int = 0
    ladder: LadderStats | None = None
    by_state: dict[str, int] = field(default_factory=dict)

    def as_note(self) -> str:
        states = " ".join(f"{k}={v}" for k, v in sorted(self.by_state.items()))
        ladder = self.ladder.as_note() if self.ladder else "ladder=skipped"
        return f"entities={self.entities} rows={self.state_rows} [{states}] {ladder}"


def run_score(session: Session, as_of: datetime) -> ScoreStats:
    stats = ScoreStats()
    stats.ladder = run_ladder(session, as_of)

    vel = velocity_mod.compute(session, as_of)
    event_days = _event_days(session, as_of)
    promo_days = _promotion_days(session, as_of)
    as_of_day = as_of.date()

    rows: list[dict[str, object]] = []
    for entity_id, facts in vel.facts.items():
        start = facts.first_seen
        day_states = replay(
            start_day=start,
            end_day=as_of_day,
            signals=vel.signals.get(entity_id, {}),
            event_days=event_days.get(entity_id, []),
            promotion_days=promo_days.get(entity_id, []),
        )
        if not day_states:
            continue
        stats.entities += 1
        for day, ds in day_states.items():
            rows.append(
                {
                    "entity_id": entity_id,
                    "day": day,
                    "state": ds.state,
                    "score": ds.score,
                    "inputs": _json(ds.inputs),
                }
            )
        final = day_states[as_of_day]
        stats.by_state[final.state] = stats.by_state.get(final.state, 0) + 1

    stats.state_rows = _upsert_states(session, rows)
    return stats


def _event_days(session: Session, as_of: datetime) -> dict[int, list[date]]:
    """Sorted distinct evidence dates per canonical entity (for activity/fading inputs)."""
    rows = session.execute(
        text(
            """
            SELECT l.entity_id AS entity_id, r.occurred_at AS occurred_at
            FROM entity_links l
            JOIN raw_events r ON r.id = l.raw_event_id
            WHERE l.rule = 'attach' AND r.occurred_at <= :as_of
            """
        ),
        {"as_of": as_of},
    ).mappings()
    canonical: dict[int, int] = {}
    days: dict[int, set[date]] = {}
    for row in rows:
        raw_id = row["entity_id"]
        if raw_id not in canonical:
            canonical[raw_id] = canonical_entity_id(session, raw_id, as_of)
        days.setdefault(canonical[raw_id], set()).add(row["occurred_at"].date())
    return {eid: sorted(ds) for eid, ds in days.items()}


def _promotion_days(session: Session, as_of: datetime) -> dict[int, list[date]]:
    rows = session.execute(
        text(
            """
            SELECT entity_id, promoted_at FROM maturity_promotions
            WHERE promoted_at <= :as_of
            """
        ),
        {"as_of": as_of},
    ).all()
    days: dict[int, set[date]] = {}
    for entity_id, promoted_at in rows:
        days.setdefault(entity_id, set()).add(promoted_at.date())
    return {eid: sorted(ds) for eid, ds in days.items()}


def _upsert_states(session: Session, rows: list[dict[str, object]]) -> int:
    if not rows:
        return 0
    session.execute(
        text(
            """
            INSERT INTO momentum_states (entity_id, day, state, score, inputs)
            VALUES (:entity_id, :day, :state, :score, CAST(:inputs AS JSONB))
            ON CONFLICT (entity_id, day)
            DO UPDATE SET state = EXCLUDED.state, score = EXCLUDED.score, inputs = EXCLUDED.inputs
            """
        ),
        rows,
    )
    return len(rows)


def _json(value: dict[str, object]) -> str:
    import json

    return json.dumps(value)
