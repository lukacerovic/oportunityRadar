"""The as-of discipline — Stage 0 exit criterion (doc 02 §5).

A future-dated event must be invisible to an ``as_of=today`` query. Runs inside a
rolled-back transaction so it never persists rows.
"""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

from sqlalchemy.orm import Session

from seismo.db import engine, events_asof
from seismo.models import RawEvent


def test_future_event_invisible_to_asof_today() -> None:
    now = datetime.now(UTC)
    with engine.connect() as conn:
        trans = conn.begin()
        session = Session(bind=conn)
        try:
            session.add_all(
                [
                    RawEvent(
                        source="test",
                        source_event_uid="past",
                        event_type="t",
                        occurred_at=now - timedelta(days=1),
                        origin="live",
                        payload={},
                    ),
                    RawEvent(
                        source="test",
                        source_event_uid="future",
                        event_type="t",
                        occurred_at=now + timedelta(days=1),
                        origin="live",
                        payload={},
                    ),
                ]
            )
            session.flush()

            visible = {e.source_event_uid for e in session.scalars(events_asof(now, source="test"))}
            assert "past" in visible, "an event dated yesterday must be visible at as_of=now"
            assert "future" not in visible, "an event dated tomorrow must be invisible at as_of=now"
        finally:
            session.close()
            trans.rollback()


def test_origin_filter_excludes_unknown_origins() -> None:
    now = datetime.now(UTC)
    with engine.connect() as conn:
        trans = conn.begin()
        session = Session(bind=conn)
        try:
            session.add(
                RawEvent(
                    source="test",
                    source_event_uid="weird-origin",
                    event_type="t",
                    occurred_at=now - timedelta(days=1),
                    origin="experimental",
                    payload={},
                )
            )
            session.flush()
            visible = {e.source_event_uid for e in session.scalars(events_asof(now, source="test"))}
            assert "weird-origin" not in visible, "default origin set must exclude unknown origins"
        finally:
            session.close()
            trans.rollback()
