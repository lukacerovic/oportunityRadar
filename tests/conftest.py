"""Shared fixtures. ``db_session`` yields a transaction that is always rolled back, so tests
touch a real Postgres (window functions, ON CONFLICT, pg_trgm are all real) without persisting.
"""

from __future__ import annotations

from collections.abc import Iterator

import pytest
from sqlalchemy.orm import Session

from seismo.db import engine


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
