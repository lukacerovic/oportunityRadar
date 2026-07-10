"""Engine, session, and the as-of discipline — the most important helpers in the codebase.

Every read that feeds analysis goes through :func:`events_asof`. Live runs pass ``now()``;
hindcasts pass historical dates. Same code path — that is the whole point (doc 02 §5).

Rules:
1. ``as_of`` is an explicit parameter; nothing analytical filters on ``ingested_at``.
2. Backfilled and seeded events are first-class: their ``occurred_at`` is historical truth.
3. The as-of discipline extends to the entity graph (doc 13 A-2): merges and category resolve
   through :func:`canonical_entity_id` / :func:`category_asof`, which apply only decisions
   justified by evidence ``occurred_at <= as_of``. A merge/category justified by a post-``as_of``
   event is invisible at ``as_of`` — this is what makes hindcasts leak-free (graph-purity test).
"""

from __future__ import annotations

from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from datetime import datetime

from sqlalchemy import Select, create_engine, select, text
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


# --- as-of entity graph (doc 13 A-2) ---------------------------------------
# Merges live in ``entity_merges`` (append-only, reversible); ``entities.merged_into`` is a
# convenience denorm that as-of code deliberately never reads. Category is time-versioned in
# ``entity_category_history``. Both resolve only decisions justified by evidence at/before as_of.

# Follow the merge chain loser -> survivor, applying only merges active and justified at/before
# ``as_of``. loser_id is PK so each entity is a loser at most once: the chain can't cycle, and
# terminates at the entity with no applicable outgoing merge (the canonical survivor).
_CANONICAL_SQL = text(
    """
    WITH RECURSIVE chain AS (
        SELECT CAST(:eid AS BIGINT) AS id, 0 AS depth
        UNION ALL
        SELECT m.survivor_id, chain.depth + 1
        FROM entity_merges m
        JOIN chain ON m.loser_id = chain.id
        WHERE m.active AND m.justified_at <= :as_of
    )
    SELECT id FROM chain ORDER BY depth DESC LIMIT 1
    """
)

_CATEGORY_ASOF_SQL = text(
    """
    SELECT category FROM entity_category_history
    WHERE entity_id = :eid AND effective_at <= :as_of
    ORDER BY effective_at DESC, id DESC
    LIMIT 1
    """
)


def canonical_entity_id(session: Session, entity_id: int, as_of: datetime) -> int:
    """Resolve ``entity_id`` to its canonical survivor **as the graph was known at** ``as_of``.

    Applies only merges that are ``active`` and justified by evidence ``occurred_at <= as_of``.
    A merge justified by a later event is invisible here, so a hindcast never sees a future
    merge (doc 13 A-2). Returns ``entity_id`` unchanged when no applicable merge exists.
    """
    result = session.execute(_CANONICAL_SQL, {"eid": entity_id, "as_of": as_of}).scalar_one()
    return int(result)


def category_asof(session: Session, entity_id: int, as_of: datetime) -> str | None:
    """The category the **canonical** entity had at ``as_of`` (drives cohorts/reach).

    Resolves the merge graph first, then reads the latest category-history row effective at or
    before ``as_of``. Returns ``None`` if the entity had no category assigned by then.
    """
    canonical = canonical_entity_id(session, entity_id, as_of)
    row = session.execute(_CATEGORY_ASOF_SQL, {"eid": canonical, "as_of": as_of}).first()
    return None if row is None else row[0]
