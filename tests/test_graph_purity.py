"""The graph-purity test (doc 04 DoD, doc 13 A-2) — the authoritative as-of purity guard.

A merge (or category change) justified by an event that occurred *after* ``as_of`` must be
invisible at ``as_of``. If it were visible, hindcasts would leak future knowledge — an entity
would appear already-merged (or already-recategorized) before the evidence for it existed.

Everything runs inside a rolled-back transaction, so real recursive-CTE SQL is exercised
without persisting rows.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from seismo.db import canonical_entity_id, category_asof, engine
from seismo.models import Entity, EntityCategoryHistory, EntityMerge


def _entity(session: Session, name: str, *, created: datetime) -> Entity:
    e = Entity(entity_type="project", canonical_name=name, created_at=created)
    session.add(e)
    session.flush()
    return e


def test_future_merge_invisible_at_asof() -> None:
    t0 = datetime(2024, 1, 1, tzinfo=UTC)
    justify = datetime(2024, 6, 1, tzinfo=UTC)  # the evidence that justifies the merge
    with engine.connect() as conn:
        trans = conn.begin()
        session = Session(bind=conn)
        try:
            survivor = _entity(session, "vllm", created=t0)
            loser = _entity(session, "vllm-inference", created=t0 + timedelta(days=1))
            session.add(
                EntityMerge(
                    loser_id=loser.id,
                    survivor_id=survivor.id,
                    justified_at=justify,
                    rule="R1",
                    confidence=0.99,
                    decided_by="auto",
                    active=True,
                )
            )
            session.flush()

            # Before the justifying evidence: the merge does not exist yet.
            before = justify - timedelta(days=1)
            assert canonical_entity_id(session, loser.id, before) == loser.id, (
                "a merge justified by a future event must be invisible at as_of"
            )
            # After the justifying evidence: loser resolves to survivor.
            after = justify + timedelta(days=1)
            assert canonical_entity_id(session, loser.id, after) == survivor.id
            # Survivor always resolves to itself.
            assert canonical_entity_id(session, survivor.id, after) == survivor.id
        finally:
            session.close()
            trans.rollback()


def test_inactive_merge_is_ignored() -> None:
    t0 = datetime(2024, 1, 1, tzinfo=UTC)
    with engine.connect() as conn:
        trans = conn.begin()
        session = Session(bind=conn)
        try:
            survivor = _entity(session, "a", created=t0)
            loser = _entity(session, "b", created=t0)
            session.add(
                EntityMerge(
                    loser_id=loser.id,
                    survivor_id=survivor.id,
                    justified_at=t0,
                    rule="R4",
                    confidence=0.85,
                    decided_by="human",
                    active=False,  # unmerged — reversibility (DR-04.2)
                )
            )
            session.flush()
            far_future = datetime(2030, 1, 1, tzinfo=UTC)
            assert canonical_entity_id(session, loser.id, far_future) == loser.id, (
                "an inactive (unmerged) merge must never resolve"
            )
        finally:
            session.close()
            trans.rollback()


def test_transitive_merge_chain_resolves_to_terminal_survivor() -> None:
    t0 = datetime(2024, 1, 1, tzinfo=UTC)
    j = datetime(2024, 2, 1, tzinfo=UTC)
    with engine.connect() as conn:
        trans = conn.begin()
        session = Session(bind=conn)
        try:
            a = _entity(session, "a", created=t0)  # terminal survivor
            b = _entity(session, "b", created=t0)
            c = _entity(session, "c", created=t0)
            session.add_all(
                [
                    EntityMerge(
                        loser_id=b.id,
                        survivor_id=a.id,
                        justified_at=j,
                        rule="R1",
                        confidence=0.99,
                        decided_by="auto",
                        active=True,
                    ),
                    EntityMerge(
                        loser_id=c.id,
                        survivor_id=b.id,
                        justified_at=j,
                        rule="R1",
                        confidence=0.99,
                        decided_by="auto",
                        active=True,
                    ),
                ]
            )
            session.flush()
            after = j + timedelta(days=1)
            assert canonical_entity_id(session, c.id, after) == a.id, (
                "c -> b -> a must resolve transitively to a"
            )
        finally:
            session.close()
            trans.rollback()


def test_category_asof_is_time_versioned_and_follows_merge() -> None:
    t0 = datetime(2024, 1, 1, tzinfo=UTC)
    with engine.connect() as conn:
        trans = conn.begin()
        session = Session(bind=conn)
        try:
            survivor = _entity(session, "s", created=t0)
            loser = _entity(session, "l", created=t0)
            session.add_all(
                [
                    EntityCategoryHistory(
                        entity_id=survivor.id,
                        category="inference-runtime",
                        effective_at=datetime(2024, 3, 1, tzinfo=UTC),
                    ),
                    EntityCategoryHistory(
                        entity_id=survivor.id,
                        category="model-foundation",
                        effective_at=datetime(2024, 9, 1, tzinfo=UTC),
                    ),
                    EntityMerge(
                        loser_id=loser.id,
                        survivor_id=survivor.id,
                        justified_at=datetime(2024, 5, 1, tzinfo=UTC),
                        rule="R1",
                        confidence=0.99,
                        decided_by="auto",
                        active=True,
                    ),
                ]
            )
            session.flush()

            # Before any category history: None.
            assert category_asof(session, survivor.id, datetime(2024, 2, 1, tzinfo=UTC)) is None
            # Between the two effective dates: the earlier category.
            assert (
                category_asof(session, survivor.id, datetime(2024, 6, 1, tzinfo=UTC))
                == "inference-runtime"
            )
            # After the second: the later category.
            assert (
                category_asof(session, survivor.id, datetime(2024, 10, 1, tzinfo=UTC))
                == "model-foundation"
            )
            # The loser, once merged, inherits the survivor's as-of category.
            assert (
                category_asof(session, loser.id, datetime(2024, 10, 1, tzinfo=UTC))
                == "model-foundation"
            )
        finally:
            session.close()
            trans.rollback()
