"""The Changes view (doc 09 §1) — deterministic daily deltas, templated, zero hallucination surface.

The system remembers what it believed and reports when its beliefs change. In v1 that report is
**not** a third LLM checkpoint (DR-09.1) — it is a templated rendering of computed diffs: momentum
state transitions, maturity promotions, the brief lifecycle, and (on Mondays) the week's gate
summary. Each row is one fixed-sentence template written to ``changes_daily`` for the dashboard to
render. Boring on purpose: honest, cheap, and impossible to hallucinate.

Runs daily after scoring (doc 09 §1). Re-runnable — a day's rows are rebuilt from scratch each run,
so a re-computed heartbeat never double-reports.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

# Heat ordering so a transition's direction is deterministic. ``fading`` is cold (a down-move from
# any warm state); ``dormant`` is the floor.
_HEAT = {"dormant": 0, "fading": 0, "simmering": 1, "accelerating": 2, "breakout": 3}
SURVIVAL_DAYS = 7  # doc 05: an entity "survives the gate" once it is 7 days old


@dataclass
class ChangesStats:
    day: date
    new_entity: int = 0
    state_up: int = 0
    state_down: int = 0
    promotion: int = 0
    brief_drafted: int = 0
    brief_published: int = 0
    gate_week: int = 0
    counts: dict[str, int] = field(default_factory=dict)

    def as_note(self) -> str:
        return (
            f"day={self.day} new={self.new_entity} up={self.state_up} down={self.state_down} "
            f"promo={self.promotion} drafts={self.brief_drafted} pub={self.brief_published} "
            f"gate_week={self.gate_week}"
        )


def compute_changes(
    session: Session, as_of: datetime | None = None, *, prev_day: date | None = None
) -> ChangesStats:
    """Compute the deterministic deltas for ``as_of``'s day and write them to ``changes_daily``."""
    as_of = as_of or datetime.now(UTC)
    day = as_of.date()
    prev = prev_day or (day - timedelta(days=1))
    stats = ChangesStats(day=day)

    session.execute(text("DELETE FROM changes_daily WHERE day = :d"), {"d": day})

    _new_entities(session, day, stats)
    _state_transitions(session, day, prev, stats)
    _promotions(session, day, stats)
    _briefs(session, day, stats)
    if day.weekday() == 0:  # Monday rollup (doc 09 §1)
        _gate_week(session, day, stats)

    return stats


def _emit(
    session: Session,
    day: date,
    kind: str,
    entity_id: int | None,
    text_line: str,
    payload: dict[str, Any],
    stats: ChangesStats,
) -> None:
    session.execute(
        text(
            """
            INSERT INTO changes_daily (day, kind, entity_id, text, payload)
            VALUES (:d, :k, :e, :t, CAST(:p AS JSONB))
            """
        ),
        {"d": day, "k": kind, "e": entity_id, "t": text_line, "p": json.dumps(payload)},
    )
    stats.counts[kind] = stats.counts.get(kind, 0) + 1
    if hasattr(stats, kind):
        setattr(stats, kind, getattr(stats, kind) + 1)


def _new_entities(session: Session, day: date, stats: ChangesStats) -> None:
    """Entities whose first attached evidence is exactly ``SURVIVAL_DAYS`` old today — they survived
    the one-day-wonder gate (doc 05). Rendered with the card one-liner when there is one."""
    born = day - timedelta(days=SURVIVAL_DAYS)
    rows = session.execute(
        text(
            """
            WITH first_seen AS (
                SELECT l.entity_id, MIN(r.occurred_at)::date AS d
                FROM entity_links l JOIN raw_events r ON r.id = l.raw_event_id
                WHERE l.rule = 'attach' GROUP BY l.entity_id
            ),
            card AS (
                SELECT DISTINCT ON (entity_id) entity_id, card->>'what_it_is' AS one_liner
                FROM comprehension_cards WHERE status = 'ok' ORDER BY entity_id, version DESC
            )
            SELECT e.id, e.canonical_name, c.one_liner
            FROM entities e JOIN first_seen fs ON fs.entity_id = e.id
            LEFT JOIN card c ON c.entity_id = e.id
            WHERE fs.d = :born AND e.merged_into IS NULL
            ORDER BY e.id
            """
        ),
        {"born": born},
    ).mappings()
    for r in rows:
        tail = f" — {r['one_liner']}" if r["one_liner"] else ""
        _emit(
            session,
            day,
            "new_entity",
            r["id"],
            f"{r['canonical_name']} survived the 7-day gate{tail}",
            {"one_liner": r["one_liner"]},
            stats,
        )


def _state_transitions(session: Session, day: date, prev: date, stats: ChangesStats) -> None:
    """Entities whose momentum state on ``day`` differs from ``prev`` — grouped ↑ / ↓ by heat."""
    rows = session.execute(
        text(
            """
            WITH today AS (
                SELECT DISTINCT ON (entity_id) entity_id, state FROM momentum_states
                WHERE day <= :day ORDER BY entity_id, day DESC
            ),
            yest AS (
                SELECT DISTINCT ON (entity_id) entity_id, state FROM momentum_states
                WHERE day <= :prev ORDER BY entity_id, day DESC
            )
            SELECT t.entity_id, e.canonical_name, t.state AS new_state,
                   COALESCE(y.state, 'dormant') AS old_state
            FROM today t JOIN entities e ON e.id = t.entity_id
            LEFT JOIN yest y ON y.entity_id = t.entity_id
            WHERE t.state <> COALESCE(y.state, 'dormant') AND e.merged_into IS NULL
            ORDER BY t.entity_id
            """
        ),
        {"day": day, "prev": prev},
    ).mappings()
    for r in rows:
        new_h = _HEAT.get(r["new_state"], 0)
        old_h = _HEAT.get(r["old_state"], 0)
        up = new_h > old_h
        arrow = "↑" if up else "↓"
        _emit(
            session,
            day,
            "state_up" if up else "state_down",
            r["entity_id"],
            f"{arrow} {r['canonical_name']}: {r['old_state']} → {r['new_state']}",
            {"old_state": r["old_state"], "new_state": r["new_state"]},
            stats,
        )


def _promotions(session: Session, day: date, stats: ChangesStats) -> None:
    rows = session.execute(
        text(
            """
            SELECT p.entity_id, e.canonical_name, p.stage, p.evidence_event
            FROM maturity_promotions p JOIN entities e ON e.id = p.entity_id
            WHERE p.promoted_at::date = :day AND e.merged_into IS NULL
            ORDER BY p.entity_id
            """
        ),
        {"day": day},
    ).mappings()
    for r in rows:
        ev = f" (event {r['evidence_event']})" if r["evidence_event"] else ""
        _emit(
            session,
            day,
            "promotion",
            r["entity_id"],
            f"{r['canonical_name']} promoted to {r['stage']}{ev}",
            {"stage": r["stage"], "evidence_event": r["evidence_event"]},
            stats,
        )


def _briefs(session: Session, day: date, stats: ChangesStats) -> None:
    drafts = session.execute(
        text(
            """
            SELECT b.id, b.entity_id, b.version, e.canonical_name
            FROM impact_briefs b JOIN entities e ON e.id = b.entity_id
            WHERE b.created_at::date = :day ORDER BY b.id
            """
        ),
        {"day": day},
    ).mappings()
    for r in drafts:
        _emit(
            session,
            day,
            "brief_drafted",
            r["entity_id"],
            f"Impact brief drafted for {r['canonical_name']} (v{r['version']}) — awaiting review",
            {"brief_id": r["id"], "version": r["version"]},
            stats,
        )
    published = session.execute(
        text(
            """
            SELECT b.id, b.entity_id, b.version, e.canonical_name
            FROM impact_briefs b JOIN entities e ON e.id = b.entity_id
            WHERE b.status = 'published' AND b.reviewed_at::date = :day ORDER BY b.id
            """
        ),
        {"day": day},
    ).mappings()
    for r in published:
        _emit(
            session,
            day,
            "brief_published",
            r["entity_id"],
            f"Impact brief published: {r['canonical_name']} (v{r['version']})",
            {"brief_id": r["id"], "version": r["version"]},
            stats,
        )


def _gate_week(session: Session, day: date, stats: ChangesStats) -> None:
    """Monday rollup: the gate decisions for the ISO week ``day`` starts (doc 09 §1)."""
    row = (
        session.execute(
            text(
                """
                SELECT
                  COUNT(*) FILTER (WHERE decision = 'pass') AS passed,
                  COUNT(*) FILTER (WHERE decision = 'suppressed') AS suppressed
                FROM gate_decisions WHERE week = :w
                """
            ),
            {"w": day},
        )
        .mappings()
        .one()
    )
    if row["passed"] == 0 and row["suppressed"] == 0:
        return
    iso = day.isocalendar()
    _emit(
        session,
        day,
        "gate_week",
        None,
        f"Gate {iso.year}-W{iso.week:02d}: {row['passed']} briefs queued, "
        f"{row['suppressed']} suppressed",
        {"passed": row["passed"], "suppressed": row["suppressed"]},
        stats,
    )
