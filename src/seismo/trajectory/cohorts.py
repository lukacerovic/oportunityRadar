"""Age-bucketed cohorts (doc 06 DR-06.3) — the reference frame for velocity percentiles.

Comparing a two-week repo's star velocity against three-year incumbents is meaningless, so an
entity is ranked only against peers of the same ``(entity_type, category, age_bucket)``. Below the
minimum cohort size the key falls back to ``(entity_type, age_bucket)`` (dropping category), and if
*that* is still too thin the entity is flagged provisional and its state capped (doc 14 §5) — the
percentile is still computed but must not be trusted to manufacture a breakout.

Everything here is as-of correct: ``category`` is read through :func:`category_asof` and an entity's
age is measured from its **first evidence** ``occurred_at`` (not ``ingested_at``), both as the graph
stood at ``as_of``.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime

from sqlalchemy import text
from sqlalchemy.orm import Session

from seismo.db import canonical_entity_id, category_asof

AGE_BUCKETS = ("0-30d", "31-90d", "91-365d", "365d+")


def age_bucket(age_days: int) -> str:
    if age_days <= 30:
        return "0-30d"
    if age_days <= 90:
        return "31-90d"
    if age_days <= 365:
        return "91-365d"
    return "365d+"


@dataclass(frozen=True)
class EntityFacts:
    """As-of facts that place an entity in a cohort. ``first_seen`` is the earliest evidence date
    across the whole merged set, so age survives merges correctly."""

    entity_id: int  # canonical
    entity_type: str
    category: str | None
    first_seen: date

    def cohort_key(self, as_of: date) -> tuple[str, str, str]:
        age = (as_of - self.first_seen).days
        return (self.entity_type, self.category or "_uncategorized", age_bucket(age))

    def fallback_key(self, as_of: date) -> tuple[str, str]:
        age = (as_of - self.first_seen).days
        return (self.entity_type, age_bucket(age))


def entity_facts(session: Session, as_of: datetime) -> dict[int, EntityFacts]:
    """Facts for every canonical entity with attached evidence at ``as_of``.

    First-seen and type are read from the raw attachment stream (as-of correct), then keyed by the
    canonical survivor so a merged loser's history folds into the survivor's age."""
    sql = text(
        """
        SELECT l.entity_id AS entity_id, MIN(r.occurred_at) AS first_seen
        FROM entity_links l
        JOIN raw_events r ON r.id = l.raw_event_id
        WHERE l.rule = 'attach' AND r.occurred_at <= :as_of
          AND r.event_type NOT IN (
              'model_snapshot', 'model_readme', 'hn_discussion',
              'pypi_metadata', 'launch_page'
          )
        GROUP BY l.entity_id
        """
    )
    # Merge each raw entity's earliest evidence into its canonical survivor.
    canonical: dict[int, int] = {}
    first_seen: dict[int, date] = {}
    for row in session.execute(sql, {"as_of": as_of}).mappings():
        raw_id = row["entity_id"]
        if raw_id not in canonical:
            canonical[raw_id] = canonical_entity_id(session, raw_id, as_of)
        cid = canonical[raw_id]
        seen: date = row["first_seen"].date()
        if cid not in first_seen or seen < first_seen[cid]:
            first_seen[cid] = seen

    # The canonical survivor's own row carries the authoritative type.
    etype: dict[int, str] = {
        row_id: row_type
        for row_id, row_type in session.execute(
            text("SELECT id, entity_type FROM entities WHERE id = ANY(:ids)"),
            {"ids": list(first_seen)},
        ).all()
    }
    return {
        cid: EntityFacts(
            entity_id=cid,
            entity_type=etype.get(cid, "unknown"),
            category=category_asof(session, cid, as_of),
            first_seen=seen,
        )
        for cid, seen in first_seen.items()
    }
