"""Council review checkpoint (doc 08 §5) — three independent perspectives on an ImpactBrief.

Pure test of the aggregation rule (never an LLM call — see council.py's docstring for why), plus
DB-backed tests of the full orchestrator against ``clean_db`` with the ``mock`` provider ($0,
deterministic), mirroring the discipline in ``test_trajectory.py``.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from seismo.checkpoints.council import ROLES, aggregate_stance, run_council

# --- pure aggregation ------------------------------------------------------


@pytest.mark.parametrize(
    "stances,expected",
    [
        (["adopt", "adopt", "adopt"], "adopt"),
        (["adopt", "adopt", "watch"], "adopt"),
        (["watch", "watch", "reject"], "watch"),
        (["reject", "reject", "reject"], "reject"),
        (["adopt", "watch", "reject"], "split"),  # no strict majority among 3 distinct votes
        ([], "split"),
    ],
)
def test_aggregate_stance(stances, expected):
    assert aggregate_stance(stances) == expected


# --- DB-backed orchestrator -------------------------------------------------


def _seed_entity(session: Session, name: str, *, p: float) -> int:
    eid = session.execute(
        text(
            "INSERT INTO entities (entity_type, canonical_name, created_at, attrs) "
            "VALUES ('project', :n, now(), '{}') RETURNING id"
        ),
        {"n": name},
    ).scalar_one()
    session.execute(
        text(
            "INSERT INTO momentum_states (entity_id, day, score, inputs, state) "
            "VALUES (:e, current_date, 1.0, :inputs, 'accelerating')"
        ),
        {"e": eid, "inputs": f'{{"P": {p}}}'},
    )
    return int(eid)


def test_run_council_mock_provider_end_to_end(clean_db: Session):
    eid = _seed_entity(clean_db, "acme/rising-repo", p=0.95)

    stats = run_council(clean_db, datetime.now(UTC), entity_id=eid)

    assert stats.candidates == 1
    assert stats.briefs_drafted == 1  # no brief existed yet — forced one
    assert stats.reviewed == 1
    assert stats.cost_usd == 0  # mock provider

    rows = clean_db.execute(
        text("SELECT role, stance, confidence, model FROM council_verdicts WHERE entity_id = :e"),
        {"e": eid},
    ).all()
    assert {r[0] for r in rows} == set(ROLES)
    assert all(r[1] in ("adopt", "watch", "reject") for r in rows)
    assert all(r[3] == "mock" for r in rows)


def test_run_council_is_idempotent(clean_db: Session):
    eid = _seed_entity(clean_db, "acme/rerun-repo", p=0.9)
    when = datetime.now(UTC)

    first = run_council(clean_db, when, entity_id=eid)
    run_council(clean_db, when, entity_id=eid)

    assert first.reviewed == 1
    n = clean_db.execute(
        text("SELECT COUNT(*) FROM council_verdicts WHERE entity_id = :e"), {"e": eid}
    ).scalar_one()
    assert n == len(ROLES)  # second run added nothing


def test_top_n_ranks_by_momentum_independent_of_gate(clean_db: Session):
    low = _seed_entity(clean_db, "acme/low-momentum", p=0.1)
    high = _seed_entity(clean_db, "acme/high-momentum", p=0.99)

    stats = run_council(clean_db, datetime.now(UTC), top_n=1)

    assert stats.candidates == 1
    reviewed = clean_db.execute(
        text("SELECT DISTINCT entity_id FROM council_verdicts")
    ).scalars().all()
    assert reviewed == [high]
    assert low not in reviewed
