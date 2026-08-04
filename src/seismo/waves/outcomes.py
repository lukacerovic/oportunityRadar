"""Did the wave take hold — measured cohort-relative, after a horizon.

This is the half that closes the loop. Detection and lead time both make a claim; this grades it,
using only measurements the system already collects. No press timestamp, no market data.

Two rules do all the work:

**Adoption, not attention.** Only ``ADOPTION_METRICS`` (usage — downloads, routed tokens) count. HN
points measure talk, and grading a wave on talk when the wave was *found* through talk-adjacent
signal would be circular.

**Cohort-relative, never absolute.** A tenfold rise means something very different for a two-week
project than for a mature one, so a wave's growth is ranked against the growth of its members' own
cohorts — the same reference frame that makes momentum percentiles meaningful.

``unmeasurable`` is a first-class verdict. PyPI is Python-only, npm is not collected at all, and a
wave made of JS tooling genuinely has nothing to measure. That must never be recorded as ``faded``:
absence of evidence is not evidence of failure, and a record that confuses the two is worth less
than no record.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import text
from sqlalchemy.orm import Session

from seismo.config import settings
from seismo.trajectory.cohorts import age_bucket
from seismo.trajectory.metrics import ADOPTION_METRICS

TOOK_HOLD = "took_hold"
FLAT = "flat"
FADED = "faded"
UNMEASURABLE = "unmeasurable"


def _median(values: list[float]) -> float | None:
    if not values:
        return None
    ordered = sorted(values)
    mid = len(ordered) // 2
    if len(ordered) % 2:
        return ordered[mid]
    return (ordered[mid - 1] + ordered[mid]) / 2


def _growth(
    session: Session, entity_ids: list[int], metric: str, start: date, end: date
) -> dict[int, float]:
    """Ratio of an entity's metric at ``end`` to its value at ``start``.

    Each endpoint takes the most recent reading at or before that day, so a sparse series (the
    OpenRouter leaderboard is top-10-only and genuinely gappy) still yields a comparison instead of
    silently dropping the entity. Entities without a positive starting value are excluded — growth
    from zero is division by zero dressed up as insight."""
    if not entity_ids:
        return {}
    rows = session.execute(
        text(
            """
            WITH s AS (
                SELECT DISTINCT ON (entity_id) entity_id, value
                FROM entity_metrics_daily
                WHERE metric = :metric AND entity_id = ANY(:ids) AND day <= :start
                ORDER BY entity_id, day DESC
            ),
            e AS (
                SELECT DISTINCT ON (entity_id) entity_id, value
                FROM entity_metrics_daily
                WHERE metric = :metric AND entity_id = ANY(:ids) AND day <= :end
                ORDER BY entity_id, day DESC
            )
            SELECT s.entity_id, s.value AS v0, e.value AS v1
            FROM s JOIN e ON e.entity_id = s.entity_id
            WHERE s.value > 0
            """
        ),
        {"metric": metric, "ids": entity_ids, "start": start, "end": end},
    ).all()
    return {int(eid): float(v1) / float(v0) for eid, v0, v1 in rows}


def _cohort_peers(session: Session, members: list[int], as_of: datetime) -> dict[str, list[int]]:
    """cohort key -> peer entity ids, for the cohorts the wave's members belong to.

    Peers are read from ``entities`` directly rather than through ``entity_facts`` because this
    needs the *whole* cohort (thousands of entities), not just the wave's members, and the exact
    merge-folding precision that matters for a member's own age is noise across a distribution."""
    rows = session.execute(
        text(
            """
            SELECT e.id, e.entity_type, e.category, MIN(r.occurred_at) AS first_seen
            FROM entities e
            JOIN entity_links l ON l.entity_id = e.id AND l.rule = 'attach'
            JOIN raw_events r ON r.id = l.raw_event_id
            WHERE e.merged_into IS NULL AND r.occurred_at <= :as_of
            GROUP BY e.id, e.entity_type, e.category
            """
        ),
        {"as_of": as_of},
    ).all()

    as_of_day = as_of.date()
    key_of: dict[int, str] = {}
    by_key: dict[str, list[int]] = {}
    for eid, etype, category, first_seen in rows:
        bucket = age_bucket((as_of_day - first_seen.date()).days)
        key = f"{etype}|{category or '_uncategorized'}|{bucket}"
        key_of[int(eid)] = key
        by_key.setdefault(key, []).append(int(eid))

    member_keys = {key_of[m] for m in members if m in key_of}
    return {k: v for k, v in by_key.items() if k in member_keys}


def evaluate_wave(
    session: Session, wave_id: int, as_of: datetime | None = None
) -> list[dict[str, object]]:
    """Score one wave against every adoption metric its members carry. Returns written rows."""
    as_of = as_of or datetime.now(UTC)
    row = session.execute(
        text("SELECT first_seen FROM wave_clusters WHERE id = :id"), {"id": wave_id}
    ).first()
    if row is None:
        return []
    detected: date = row[0]
    horizon = settings.wave_outcome_horizon_days
    end = detected + timedelta(days=horizon)

    members = list(
        session.execute(
            text("SELECT entity_id FROM wave_members WHERE wave_id = :id"), {"id": wave_id}
        ).scalars()
    )
    if not members:
        return []

    written: list[dict[str, object]] = []
    cohorts = _cohort_peers(session, members, as_of)
    peer_ids = sorted({i for ids in cohorts.values() for i in ids})

    for metric in sorted(ADOPTION_METRICS):
        member_growth = _growth(session, members, metric, detected, end)
        too_early = as_of.date() < end

        if not member_growth:
            verdict, wave_g, cohort_g, pctl = UNMEASURABLE, None, None, None
            detail: dict[str, object] = {
                "reason": "no members carry this metric",
                "members_measured": 0,
                "horizon_reached": not too_early,
            }
        else:
            peer_growth = _growth(session, peer_ids, metric, detected, end)
            # Peers exclude the wave's own members, or the wave would be graded partly against
            # itself and a large wave would always look average.
            peer_values = [g for eid, g in peer_growth.items() if eid not in member_growth]
            wave_g = _median(list(member_growth.values()))
            cohort_g = _median(peer_values)
            pctl = (
                sum(1 for g in peer_values if g < (wave_g or 0)) / len(peer_values)
                if peer_values
                else None
            )

            band = settings.wave_outcome_flat_band
            if cohort_g is None:
                # Growth is real but nothing to compare it to; refuse to call it either way.
                verdict = UNMEASURABLE
            elif wave_g is not None and wave_g > cohort_g * (1 + band):
                verdict = TOOK_HOLD
            elif wave_g is not None and wave_g < cohort_g * (1 - band):
                verdict = FADED
            else:
                verdict = FLAT
            if too_early:
                # The horizon hasn't elapsed; record the reading but never a verdict from it.
                verdict = UNMEASURABLE
            detail = {
                "members_measured": len(member_growth),
                "peers_measured": len(peer_values),
                "horizon_reached": not too_early,
                "cohorts": sorted(cohorts),
            }

        session.execute(
            text(
                """
                INSERT INTO wave_outcomes
                  (wave_id, evaluated_at, horizon_days, metric, wave_growth, cohort_growth,
                   percentile, verdict, detail)
                VALUES (:wave_id, :evaluated_at, :horizon, :metric, :wave_growth, :cohort_growth,
                        :percentile, :verdict, CAST(:detail AS jsonb))
                ON CONFLICT (wave_id, horizon_days, metric) DO UPDATE
                  SET evaluated_at = EXCLUDED.evaluated_at,
                      wave_growth = EXCLUDED.wave_growth,
                      cohort_growth = EXCLUDED.cohort_growth,
                      percentile = EXCLUDED.percentile,
                      verdict = EXCLUDED.verdict,
                      detail = EXCLUDED.detail
                """
            ),
            {
                "wave_id": wave_id,
                "evaluated_at": as_of,
                "horizon": horizon,
                "metric": metric,
                "wave_growth": wave_g,
                "cohort_growth": cohort_g,
                "percentile": pctl,
                "verdict": verdict,
                "detail": json.dumps(detail),
            },
        )
        written.append({"metric": metric, "verdict": verdict, "wave_growth": wave_g})
    return written


def run_outcomes(session: Session, as_of: datetime | None = None) -> dict[str, int]:
    """Evaluate every live wave."""
    as_of = as_of or datetime.now(UTC)
    wave_ids = list(
        session.execute(
            text("SELECT id FROM wave_clusters WHERE merged_into IS NULL ORDER BY id")
        ).scalars()
    )
    rows = sum(len(evaluate_wave(session, wid, as_of)) for wid in wave_ids)
    return {"waves": len(wave_ids), "outcomes": rows}
