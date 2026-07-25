"""Shared fixtures. ``db_session`` yields a transaction that is always rolled back, so tests
touch a real Postgres (window functions, ON CONFLICT, pg_trgm are all real) without persisting.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from seismo.db import engine

# Tables cleared by ``clean_db`` so a test runs against an isolated slate. resolve()/seed-load
# are global by design and the shared dev DB carries committed events; deletions live inside the
# rolled-back transaction, so real data returns on rollback. Order = dependents before parents.
_CLEAR_TABLES = [
    "entity_merge_queue",
    "entity_merges",
    "entity_category_history",
    "entity_themes",
    "entity_links",
    "momentum_states",
    "maturity_promotions",
    "entity_metrics_daily",
    "comprehension_cards",
    "gate_decisions",
    "brief_scores",
    "council_verdicts",
    "impact_briefs",
    "changes_daily",
    "calibration_snapshots",
    "hindcast_runs",
    "entity_graph_edges",
    "entity_semantic_edges",
    "discovery_triage_decisions",
    "entities",
    "raw_events",
]


@pytest.fixture
def db_session() -> Iterator[Session]:
    conn = engine.connect()
    trans = conn.begin()
    session = Session(bind=conn)
    try:
        yield session
    finally:
        session.close()
        trans.rollback()
        conn.close()


@pytest.fixture
def clean_db(db_session: Session) -> Session:
    """A ``db_session`` with the entity/event tables emptied, for tests that exercise the global
    resolve/seed engines and need to assert exact counts."""
    for table in _CLEAR_TABLES:
        db_session.execute(text(f"DELETE FROM {table}"))
    db_session.flush()
    return db_session
