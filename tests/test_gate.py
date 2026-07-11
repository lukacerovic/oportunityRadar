"""Significance gate (doc 07) on synthetic momentum — the dev DB is all-dormant, so the gate is
exercised against hand-built momentum_states / reach_links. Covers the A-6 hard-reach exclusion,
the A-12 pending-card block, the doc-14 provisional exclusion, top-K budgeting, and the H3 flop
assertion (attention-only spike with thin reach must be suppressed, never briefed)."""

from __future__ import annotations

from datetime import UTC, date, datetime

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from seismo.models import (
    ComprehensionCard,
    Entity,
    EntityCategoryHistory,
    EntityLink,
    MomentumState,
    RawEvent,
)
from seismo.significance.gate import _momentum, _score, parse_week, run_gate

WEEK_START = date(2026, 6, 29)  # a Monday
MID_WEEK = date(2026, 7, 1)
AS_OF = datetime(2026, 7, 5, 23, 59, 59, tzinfo=UTC)
FIRST_SEEN = datetime(2026, 5, 1, tzinfo=UTC)  # age ~65d < 180d novelty window


@pytest.fixture(autouse=True)
def _isolated(clean_db: Session) -> Session:
    return clean_db


def _reach(session: Session, category: str, n_lines: int = 1, core: bool = False) -> None:
    for i in range(n_lines):
        session.execute(
            text(
                "INSERT INTO reach_links (category,ticker,revenue_line,relation,core) "
                "VALUES (:c,:t,:l,'demand_risk',:core)"
            ),
            {"c": category, "t": "TST", "l": f"line{i}", "core": core and i == 0},
        )


def _entity(
    session: Session,
    *,
    category: str,
    state: str = "breakout",
    p: float = 0.97,
    provisional: bool = False,
    card: str | None = "ok",
    first_seen: datetime = FIRST_SEEN,
) -> int:
    e = Entity(
        entity_type="project", canonical_name=f"e{_entity.n}", created_at=first_seen, attrs={}
    )
    _entity.n += 1  # type: ignore[attr-defined]
    session.add(e)
    session.flush()
    rev = RawEvent(
        source="github",
        source_event_uid=f"x:{e.id}",
        event_type="repo_discovered",
        occurred_at=first_seen,
        origin="live",
        payload={},
    )
    session.add(rev)
    session.flush()
    session.add(
        EntityLink(
            entity_id=e.id,
            raw_event_id=rev.id,
            rule="attach",
            confidence=1.0,
            evidence_occurred_at=first_seen,
        )
    )
    session.add(EntityCategoryHistory(entity_id=e.id, category=category, effective_at=first_seen))
    session.add(
        MomentumState(
            entity_id=e.id,
            day=MID_WEEK,
            state=state,
            score=p,
            inputs={"P": p, "provisional": provisional, "cohort_n": 20},
        )
    )
    if card is not None:
        session.add(
            ComprehensionCard(
                entity_id=e.id, version=1, as_of=AS_OF, card={}, model="mock", status=card
            )
        )
    session.flush()
    return e.id


_entity.n = 0  # type: ignore[attr-defined]


def _decisions(session: Session) -> dict[int, tuple[str, str | None]]:
    rows = session.execute(
        text("SELECT entity_id, decision, components->>'reason' AS reason FROM gate_decisions")
    )
    return {r.entity_id: (r.decision, r.reason) for r in rows}


# --- formula (locks the arithmetic) ----------------------------------------


def test_score_and_momentum_formula() -> None:
    # breakout P=1 → M=1.0; R=1, N=1 → score = 1.0 * (0.4+0.6) * (0.4+0.6) = 1.0
    assert _momentum(type("C", (), {"peak_state": "breakout", "p_peak": 1.0})()) == 1.0
    assert _score(1.0, 1.0, 1.0) == pytest.approx(1.0)
    # zero R/N still floored inside the score (0.4 each) — never zeroed once eligible
    assert _score(1.0, 0.5, 0.3) == pytest.approx(1.0 * 0.7 * 0.58)


# --- reach eligibility (A-6) -----------------------------------------------


def test_unmapped_reach_is_hard_suppressed(clean_db: Session) -> None:
    eid = _entity(clean_db, category="eval-tooling")  # no reach_links inserted for it
    stats = run_gate(clean_db, WEEK_START, now=AS_OF)
    clean_db.flush()
    assert stats.passed == 0 and stats.suppressed_unmapped == 1
    assert stats.map_gaps == {"eval-tooling": 1}
    assert _decisions(clean_db)[eid] == ("suppressed", "unmapped_reach")


def test_mapped_entity_passes(clean_db: Session) -> None:
    _reach(clean_db, "inference-runtime", n_lines=1)
    eid = _entity(clean_db, category="inference-runtime")
    stats = run_gate(clean_db, WEEK_START, now=AS_OF)
    clean_db.flush()
    assert stats.passed == 1
    assert _decisions(clean_db)[eid][0] == "pass"


# --- H3: attention-only flop must be suppressed ----------------------------


def test_h3_flop_high_momentum_thin_reach_suppressed(clean_db: Session) -> None:
    # Reflection-70B-style: breakout momentum, top percentile — but its category touches no map
    # surface. It must be excluded before scoring, never briefed (doc 07 §4 / A-6).
    eid = _entity(clean_db, category="prompt-tooling", state="breakout", p=0.99)
    stats = run_gate(clean_db, WEEK_START, now=AS_OF)
    clean_db.flush()
    assert stats.passed == 0
    assert _decisions(clean_db)[eid] == ("suppressed", "unmapped_reach")


# --- provisional cold-start states never qualify (doc 14 §5) ----------------


def test_provisional_state_is_not_a_candidate(clean_db: Session) -> None:
    _reach(clean_db, "inference-runtime")
    _entity(clean_db, category="inference-runtime", state="accelerating", provisional=True)
    stats = run_gate(clean_db, WEEK_START, now=AS_OF)
    clean_db.flush()
    assert stats.candidates == 0 and stats.passed == 0


# --- A-12: a pending card can never be briefed ------------------------------


def test_pending_card_blocks_pass(clean_db: Session) -> None:
    _reach(clean_db, "inference-runtime", n_lines=3)  # R would be 1.0
    eid = _entity(clean_db, category="inference-runtime", card="pending")
    stats = run_gate(clean_db, WEEK_START, now=AS_OF)
    clean_db.flush()
    assert stats.passed == 0 and stats.suppressed_pending == 1
    assert _decisions(clean_db)[eid] == ("suppressed", "card_pending")


# --- budget: top-K pass, the rest are suppressed with reason 'budget' -------


def test_top_k_budget(clean_db: Session) -> None:
    from seismo.config import settings

    _reach(clean_db, "inference-runtime", n_lines=3)
    k = settings.briefs_per_week
    # k+2 eligible breakout entities, distinct ages so novelty ranking is deterministic.
    for i in range(k + 2):
        _entity(
            clean_db,
            category="inference-runtime",
            first_seen=datetime(2026, 5, 1 + i, tzinfo=UTC),
        )
    stats = run_gate(clean_db, WEEK_START, now=AS_OF)
    clean_db.flush()
    assert stats.candidates == k + 2
    assert stats.passed == k
    assert stats.suppressed_budget == 2
    reasons = {d[1] for d in _decisions(clean_db).values() if d[0] == "suppressed"}
    assert reasons == {"budget"}


# --- re-runnable: a second run for the same week replaces, not appends ------


def test_gate_is_rerunnable(clean_db: Session) -> None:
    _reach(clean_db, "inference-runtime")
    _entity(clean_db, category="inference-runtime")
    run_gate(clean_db, WEEK_START, now=AS_OF)
    clean_db.flush()
    run_gate(clean_db, WEEK_START, now=AS_OF)
    clean_db.flush()
    n = clean_db.execute(text("SELECT COUNT(*) FROM gate_decisions")).scalar_one()
    assert n == 1  # one row per candidate, not two


def test_parse_week() -> None:
    assert parse_week("2026-W27") == date(2026, 6, 29)
    assert parse_week("2026-w27") == date(2026, 6, 29)
