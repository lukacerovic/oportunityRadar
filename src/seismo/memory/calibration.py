"""Momentum-call review (doc 09 §3) — the automated, monthly half of the calibration loop.

This is the cheap, fully-deterministic instrument that grades the *trajectory* layer against reality
without any human judgment: of the entities the system once called ``breakout``, how many were still
alive months later? Of the ones it called ``fading``, how many quietly re-accelerated (a false
alarm)? Both are ratios over momentum history, written to ``calibration_snapshots`` as a time series
the dashboard trends. A drifting survival rate is the signal that the doc-06 thresholds are too
loose or too tight — the system telling on itself.

Brief forward-scoring (doc 09 §2) is the *other* half and is a human ritual (``memory.scoring``);
this module never touches briefs.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import text
from sqlalchemy.orm import Session

# doc 09 §3: a breakout is "survived" if, ≥90 days on, the entity is still simmering or hotter.
SURVIVAL_LOOKBACK_DAYS = 90
ALIVE_STATES = ("simmering", "accelerating", "breakout")
# A fade is a "false alarm" if the entity re-accelerated within 60 days of the call.
FADE_FORWARD_DAYS = 60
REACCEL_STATES = ("accelerating", "breakout")


@dataclass
class CalibrationStats:
    day: date
    breakout_survival: float | None = None
    breakout_n: int = 0
    fade_reaccel: float | None = None
    fade_n: int = 0
    notes: list[str] = field(default_factory=list)

    def as_note(self) -> str:
        bs = "n/a" if self.breakout_survival is None else f"{self.breakout_survival:.0%}"
        fr = "n/a" if self.fade_reaccel is None else f"{self.fade_reaccel:.0%}"
        return (
            f"day={self.day} breakout_survival={bs} (n={self.breakout_n}) "
            f"fade_reaccel={fr} (n={self.fade_n})"
        )


def run_momentum_review(session: Session, as_of: datetime | None = None) -> CalibrationStats:
    """Compute the two momentum-calibration ratios as of ``as_of`` and upsert them as a snapshot."""
    as_of = as_of or datetime.now(UTC)
    day = as_of.date()
    stats = CalibrationStats(day=day)

    surv, surv_n, surv_detail = _breakout_survival(session, as_of)
    stats.breakout_survival, stats.breakout_n = surv, surv_n
    _write(session, day, "breakout_survival", surv, surv_n, surv_detail)
    if surv_n == 0:
        stats.notes.append("no breakout calls old enough to score (need ≥90d of history)")

    fade, fade_n, fade_detail = _fade_reaccel(session, as_of)
    stats.fade_reaccel, stats.fade_n = fade, fade_n
    _write(session, day, "fade_reaccel", fade, fade_n, fade_detail)
    if fade_n == 0:
        stats.notes.append("no fade calls old enough to score (need ≥60d of forward history)")

    return stats


def _breakout_survival(
    session: Session, as_of: datetime
) -> tuple[float | None, int, dict[str, object]]:
    """Share of entities whose FIRST breakout was ≥90d ago that are still simmering+ today."""
    cutoff = (as_of - timedelta(days=SURVIVAL_LOOKBACK_DAYS)).date()
    rows = session.execute(
        text(
            """
            WITH first_breakout AS (
                SELECT entity_id, MIN(day) AS first_day
                FROM momentum_states WHERE state = 'breakout' AND day <= :cutoff
                GROUP BY entity_id
            ),
            latest AS (
                SELECT DISTINCT ON (entity_id) entity_id, state
                FROM momentum_states WHERE day <= :as_of_day
                ORDER BY entity_id, day DESC
            )
            SELECT fb.entity_id, l.state
            FROM first_breakout fb JOIN latest l ON l.entity_id = fb.entity_id
            """
        ),
        {"cutoff": cutoff, "as_of_day": as_of.date()},
    ).all()
    n = len(rows)
    if n == 0:
        return None, 0, {}
    alive = sum(1 for _, state in rows if state in ALIVE_STATES)
    return alive / n, n, {"alive": alive, "total": n, "lookback_days": SURVIVAL_LOOKBACK_DAYS}


def _fade_reaccel(session: Session, as_of: datetime) -> tuple[float | None, int, dict[str, object]]:
    """Share of fade calls (≥60d ago) that re-accelerated within 60 days — a false-alarm rate."""
    cutoff = (as_of - timedelta(days=FADE_FORWARD_DAYS)).date()
    fades = session.execute(
        text(
            """
            SELECT entity_id, MIN(day) AS fade_day
            FROM momentum_states WHERE state = 'fading' AND day <= :cutoff
            GROUP BY entity_id
            """
        ),
        {"cutoff": cutoff},
    ).all()
    n = len(fades)
    if n == 0:
        return None, 0, {}
    reaccel = 0
    for entity_id, fade_day in fades:
        window_end = fade_day + timedelta(days=FADE_FORWARD_DAYS)
        hit = session.execute(
            text(
                """
                SELECT 1 FROM momentum_states
                WHERE entity_id = :e AND day > :fade AND day <= :end
                  AND state = ANY(:states) LIMIT 1
                """
            ),
            {"e": entity_id, "fade": fade_day, "end": window_end, "states": list(REACCEL_STATES)},
        ).first()
        if hit is not None:
            reaccel += 1
    return reaccel / n, n, {"reaccelerated": reaccel, "total": n, "forward_days": FADE_FORWARD_DAYS}


def _write(
    session: Session,
    day: date,
    metric: str,
    value: float | None,
    sample_n: int,
    detail: dict[str, object],
) -> None:
    import json

    session.execute(
        text(
            """
            INSERT INTO calibration_snapshots (day, metric, value, sample_n, detail)
            VALUES (:d, :m, :v, :n, CAST(:detail AS JSONB))
            ON CONFLICT (day, metric) DO UPDATE
              SET value = EXCLUDED.value, sample_n = EXCLUDED.sample_n,
                  detail = EXCLUDED.detail, created_at = now()
            """
        ),
        {"d": day, "m": metric, "v": value, "n": sample_n, "detail": json.dumps(detail)},
    )
