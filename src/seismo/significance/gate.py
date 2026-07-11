"""Significance gate (doc 07) — which entities earn an Impact Brief this week, under a fixed budget.

**Fully deterministic — no LLM (DR-07.1).** The model's judgment enters only *after* the gate, to
write the brief; letting a model rank importance would reintroduce vibes at the exact chokepoint the
budget exists to protect. The gate is arithmetic over three components:

- **Momentum (M)** — the week's peak state (breakout=1.0, accelerating=0.7) scaled by the peak
  velocity percentile ``P``.
- **Reach (R)** — does the entity's category touch the exposure map? **R = 0 is a hard eligibility
  exclusion (doc 13 A-6)**, not a floor: a zero-reach entity is never scored and never passed — it
  gets a ``suppressed`` / ``unmapped_reach`` decision and rolls into the weekly **map-gaps** list,
  which forces the map to grow deliberately. Among eligible entities R ∈ {0.5, 1.0}.
- **Novelty (N)** — a pioneer proxy: first-3 in the (category, age<180d) cohort → 1.0; a small
  cohort → 0.6; a crowded one → 0.3. Crowded-category clones rank low even when fast.

``Score = M × (0.4 + 0.6·R) × (0.4 + 0.6·N)`` over the *eligible* set. Top-K (``briefs_per_week``)
pass; the rest are ``suppressed``. **Every** candidate — passed or suppressed — gets a
``gate_decisions`` audit row with the full component breakdown, because trust in the gate comes from
being able to inspect what it *didn't* show you (idea-spec principle 7). Provisional cold-start
states never qualify (doc 14 §5) and a ``pending`` comprehension card can never be briefed (A-12).

As-of correct: the run scores at the week's end; category/graph are read through the doc-06 cohort
facts (``category_asof``), so re-running a past week is a pure function of events ≤ that week's end.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import text
from sqlalchemy.orm import Session

from seismo.config import settings
from seismo.trajectory.cohorts import EntityFacts, entity_facts

# Peak-state → Momentum base. Only breakout/accelerating qualify (doc 07 §1); lower states never.
_STATE_RANK = {"accelerating": 2, "breakout": 3}


@dataclass
class Candidate:
    entity_id: int
    peak_state: str
    p_peak: float


@dataclass
class GateStats:
    week: date
    candidates: int = 0
    passed: int = 0
    suppressed_budget: int = 0
    suppressed_unmapped: int = 0
    suppressed_pending: int = 0
    map_gaps: dict[str, int] = field(default_factory=dict)

    def as_note(self) -> str:
        gaps = ", ".join(f"{c}×{n}" for c, n in sorted(self.map_gaps.items(), key=lambda x: -x[1]))
        return (
            f"week={self.week} candidates={self.candidates} pass={self.passed} "
            f"suppressed(budget={self.suppressed_budget} unmapped={self.suppressed_unmapped} "
            f"pending={self.suppressed_pending}) map_gaps=[{gaps}]"
        )


def parse_week(value: str | None, *, now: datetime | None = None) -> date:
    """``2026-W28`` → that ISO week's Monday date. ``None`` → the current ISO week's Monday."""
    now = now or datetime.now(UTC)
    if value is None:
        iso = now.isocalendar()
        return date.fromisocalendar(iso.year, iso.week, 1)
    year_s, week_s = value.upper().split("-W")
    return date.fromisocalendar(int(year_s), int(week_s), 1)


def run_gate(session: Session, week_start: date, *, now: datetime | None = None) -> GateStats:
    """Score the week's ``accelerating``/``breakout`` entities and write ``gate_decisions`` rows."""
    week_end_day = week_start + timedelta(days=6)
    as_of = datetime.combine(week_end_day, datetime.max.time()).replace(tzinfo=UTC)
    stats = GateStats(week=week_start)

    candidates = _candidates(session, week_start, week_end_day)
    stats.candidates = len(candidates)
    # Re-runnable: a week's decisions are rebuilt from scratch each run.
    session.execute(text("DELETE FROM gate_decisions WHERE week = :w"), {"w": week_start})
    if not candidates:
        return stats

    facts = entity_facts(session, as_of)
    novelty = _novelty_scores(facts, as_of.date())
    recent_brief = _recently_briefed(session, as_of)
    card_ok = _cards_ok(session, [c.entity_id for c in candidates])

    scored: list[tuple[Candidate, dict[str, object], float]] = []
    for c in candidates:
        if c.entity_id in recent_brief:
            continue  # a fresh published brief already covers it (doc 07 §1)
        category = facts[c.entity_id].category if c.entity_id in facts else None
        lines, has_core = _reach(session, category)
        m = _momentum(c)
        n = novelty.get(c.entity_id, 0.3)

        if lines == 0:  # A-6: zero reach is excluded before scoring, not floored
            _write(
                session,
                c.entity_id,
                week_start,
                "suppressed",
                0.0,
                _components(c, m, 0.0, n, 0.0, category, lines, has_core, "unmapped_reach"),
            )
            stats.suppressed_unmapped += 1
            if category:
                stats.map_gaps[category] = stats.map_gaps.get(category, 0) + 1
            continue

        r = 1.0 if (lines >= 3 or has_core) else 0.5
        score = _score(m, r, n)
        comps = _components(c, m, r, n, score, category, lines, has_core, None)
        if not card_ok.get(c.entity_id, False):  # A-12: never brief a pending/absent card
            comps["reason"] = "card_pending"
            _write(session, c.entity_id, week_start, "suppressed", score, comps)
            stats.suppressed_pending += 1
            continue
        scored.append((c, comps, score))

    scored.sort(key=lambda x: x[2], reverse=True)
    for rank, (c, comps, score) in enumerate(scored):
        if rank < settings.briefs_per_week:
            _write(session, c.entity_id, week_start, "pass", score, comps)
            stats.passed += 1
        else:
            comps = {**comps, "reason": "budget"}
            _write(session, c.entity_id, week_start, "suppressed", score, comps)
            stats.suppressed_budget += 1
    return stats


def _candidates(session: Session, week_start: date, week_end_day: date) -> list[Candidate]:
    """Entities whose momentum reached a NON-provisional accelerating/breakout during the week.

    Provisional cold-start states (doc 14 §5) are ignored — they may show as simmering on the Radar
    but can never spend a brief. Peak state + percentile are taken over qualifying days only."""
    rows = session.execute(
        text(
            """
            SELECT entity_id, state, COALESCE((inputs->>'P')::float, 0.0) AS p
            FROM momentum_states
            WHERE day BETWEEN :ws AND :we
              AND state IN ('accelerating', 'breakout')
              AND COALESCE((inputs->>'provisional')::boolean, false) = false
            """
        ),
        {"ws": week_start, "we": week_end_day},
    ).mappings()
    best: dict[int, Candidate] = {}
    for row in rows:
        eid = row["entity_id"]
        cur = best.get(eid)
        rank = _STATE_RANK[row["state"]]
        if cur is None or rank > _STATE_RANK[cur.peak_state] or row["p"] > cur.p_peak:
            peak_state = (
                row["state"]
                if cur is None or rank >= _STATE_RANK[cur.peak_state]
                else cur.peak_state
            )
            p_peak = max(row["p"], cur.p_peak if cur else 0.0)
            best[eid] = Candidate(entity_id=eid, peak_state=peak_state, p_peak=p_peak)
    return list(best.values())


def _momentum(c: Candidate) -> float:
    base = settings.gate_m_breakout if c.peak_state == "breakout" else settings.gate_m_accelerating
    floor = settings.gate_m_percentile_floor
    return base * (floor + (1.0 - floor) * max(0.0, min(1.0, c.p_peak)))


def _score(m: float, r: float, n: float) -> float:
    rf, nf = settings.gate_score_reach_floor, settings.gate_score_novelty_floor
    return m * (rf + (1.0 - rf) * r) * (nf + (1.0 - nf) * n)


def _reach(session: Session, category: str | None) -> tuple[int, bool]:
    """(# distinct revenue lines touched, any core) for a category via reach_links (doc 07 §2)."""
    if not category:
        return (0, False)
    row = (
        session.execute(
            text(
                """
            SELECT COUNT(DISTINCT ticker || ':' || revenue_line) AS lines,
                   COALESCE(bool_or(core), false) AS has_core
            FROM reach_links WHERE category = :c
            """
            ),
            {"c": category},
        )
        .mappings()
        .one()
    )
    return (int(row["lines"]), bool(row["has_core"]))


def _novelty_scores(facts: dict[int, EntityFacts], as_of: date) -> dict[int, float]:
    """N per entity (doc 07 §2): first-3 in the (category, age<180d) cohort → 1.0; small cohort
    (<10) → 0.6; crowded → 0.3. 'First' = earliest first-evidence (the pioneers of the category)."""
    window = settings.gate_novelty_cohort_days
    cohorts: dict[str, list[tuple[date, int]]] = {}
    for f in facts.values():
        if f.category is None:
            continue
        age = (as_of - f.first_seen).days
        if age < window:
            cohorts.setdefault(f.category, []).append((f.first_seen, f.entity_id))
    out: dict[int, float] = {}
    for members in cohorts.values():
        members.sort(key=lambda x: (x[0], x[1]))  # earliest first, id tiebreak
        size = len(members)
        for i, (_, eid) in enumerate(members):
            out[eid] = 1.0 if i < 3 else (0.6 if size < 10 else 0.3)
    return out


def _recently_briefed(session: Session, as_of: datetime) -> set[int]:
    cutoff = as_of - timedelta(days=settings.gate_rebrief_days)
    rows = session.execute(
        text(
            """
            SELECT DISTINCT entity_id FROM impact_briefs
            WHERE status = 'published' AND created_at > :cutoff
            """
        ),
        {"cutoff": cutoff},
    ).scalars()
    return set(rows)


def _cards_ok(session: Session, entity_ids: list[int]) -> dict[int, bool]:
    """Whether each entity's latest card is status='ok' (A-12: pending/absent can't be briefed)."""
    if not entity_ids:
        return {}
    rows = session.execute(
        text(
            """
            SELECT DISTINCT ON (entity_id) entity_id, status
            FROM comprehension_cards
            WHERE entity_id = ANY(:ids)
            ORDER BY entity_id, version DESC
            """
        ),
        {"ids": entity_ids},
    ).mappings()
    return {row["entity_id"]: row["status"] == "ok" for row in rows}


def _components(
    c: Candidate,
    m: float,
    r: float,
    n: float,
    score: float,
    category: str | None,
    lines: int,
    has_core: bool,
    reason: str | None,
) -> dict[str, object]:
    comps: dict[str, object] = {
        "M": round(m, 4),
        "R": r,
        "N": round(n, 4),
        "score": round(score, 4),
        "peak_state": c.peak_state,
        "p_peak": round(c.p_peak, 4),
        "category": category,
        "reach_lines": lines,
        "reach_core": has_core,
    }
    if reason:
        comps["reason"] = reason
    return comps


def _write(
    session: Session,
    entity_id: int,
    week: date,
    decision: str,
    score: float,
    components: dict[str, object],
) -> None:
    session.execute(
        text(
            """
            INSERT INTO gate_decisions (entity_id, week, decision, score, components)
            VALUES (:e, :w, :d, :s, CAST(:c AS JSONB))
            """
        ),
        {"e": entity_id, "w": week, "d": decision, "s": score, "c": _json(components)},
    )


def _json(value: dict[str, object]) -> str:
    import json

    return json.dumps(value)
