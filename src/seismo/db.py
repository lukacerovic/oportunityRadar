"""Engine, session, and the as-of discipline — the most important helpers in the codebase.

Every read that feeds analysis goes through :func:`events_asof`. Live runs pass ``now()``;
hindcasts pass historical dates. Same code path — that is the whole point (doc 02 §5).

Rules:
1. ``as_of`` is an explicit parameter; nothing analytical filters on ``ingested_at``.
2. Backfilled and seeded events are first-class: their ``occurred_at`` is historical truth.
3. The as-of discipline extends to the entity graph in Stage 2 (doc 13 A-2); until migration
   0002 lands there is no merge graph to resolve, so this module only guards event visibility.
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from datetime import datetime

from sqlalchemy import Select, create_engine, select
from sqlalchemy.orm import Session, sessionmaker

from seismo.config import settings
from seismo.models import RawEvent

engine = create_engine(settings.database_url, pool_pre_ping=True, future=True)
SessionLocal = sessionmaker(bind=engine, expire_on_commit=False, future=True)


@contextmanager
def session_scope() -> Iterator[Session]:
    """Transactional session: commit on success, roll back on error, always close."""
    session = SessionLocal()
    try:
        yield session
        session.commit()
    except Exception:
        session.rollback()
        raise
    finally:
        session.close()


def events_asof(
    as_of: datetime,
    *,
    source: str | None = None,
    origins: Sequence[str] | None = None,
) -> Select[tuple[RawEvent]]:
    """Build the canonical as-of visibility query.

    Returns a ``Select`` (composable) rather than results, so callers can add filters and
    still route every analytical read through the single ``occurred_at <= as_of`` guard.

    ``origins`` defaults to the live-analysis set (live + backfill + seed). Hindcast runners
    may narrow it, but no caller may widen the time bound.
    """
    allowed = list(origins) if origins is not None else ["live", "backfill", "seed"]
    stmt = select(RawEvent).where(RawEvent.occurred_at <= as_of).where(RawEvent.origin.in_(allowed))
    if source is not None:
        stmt = stmt.where(RawEvent.source == source)
    return stmt.order_by(RawEvent.occurred_at)
