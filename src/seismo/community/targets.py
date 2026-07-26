"""Target selection for community research.

This layer researches entities we already know; it does not discover new entities.
The selector returns a bounded due set so daily runs stay within API budget.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

# Anchor key each source requires on an entity to be researchable. HN searches by name/URL and is
# omitted (no requirement). Keep in sync with each client's ``applies_to``.
_SOURCE_ANCHOR = {"github": "github", "hf": "hf"}


@dataclass(frozen=True)
class CommunityTarget:
    entity_id: int
    canonical_name: str
    entity_type: str
    category: str | None
    anchors: dict[str, str]
    owner: str | None
    description: str | None
    card: dict[str, Any] | None
    state: str
    last_researched_at: datetime | None
    last_status: str | None


def select_community_targets(
    session: Session,
    source: str,
    *,
    as_of: datetime,
    limit: int | None = None,
    entity_id: int | None = None,
    force: bool = False,
) -> list[CommunityTarget]:
    """Return existing entities due for community research.

    Cadence:
    - no row: now
    - breakout/accelerating: 1 day
    - simmering: 3 days
    - fading/dormant: 14 days
    - not_found: 7 days
    - failed: 1 day
    """
    sql_limit = limit if force or entity_id is not None else None
    # Sparse sources must have their anchor requirement pushed into SQL, else ``limit`` slices the
    # global top-N by momentum and the anchor filter (runner ``applies_to``) then discards most of
    # it — starving rare sources like HF (110 of ~18k entities). HN searches by name/URL and needs
    # no anchor. Uses ``jsonb_exists`` not the ``?`` operator to avoid DBAPI paramstyle clashes.
    anchor_key = _SOURCE_ANCHOR.get(source)
    rows = (
        session.execute(
            text(
                """
                WITH latest_card AS (
                  SELECT DISTINCT ON (entity_id) entity_id, card
                  FROM comprehension_cards
                  WHERE as_of <= :as_of AND status = 'ok'
                  ORDER BY entity_id, version DESC
                ),
                latest_state AS (
                  SELECT DISTINCT ON (entity_id) entity_id, state, inputs
                  FROM momentum_states
                  WHERE day <= :as_of_day
                  ORDER BY entity_id, day DESC
                ),
                latest_community AS (
                  SELECT DISTINCT ON (entity_id, source)
                         entity_id, source, status, researched_at
                  FROM entity_community_research
                  WHERE source = :source AND researched_at <= :as_of
                  ORDER BY entity_id, source, researched_at DESC, id DESC
                )
                SELECT e.id, e.canonical_name, e.entity_type, e.category, e.attrs,
                       COALESCE(ls.state, 'dormant') AS state,
                       lc.card,
                       lcr.status AS last_status,
                       lcr.researched_at AS last_researched_at
                FROM entities e
                LEFT JOIN latest_card lc ON lc.entity_id = e.id
                LEFT JOIN latest_state ls ON ls.entity_id = e.id
                LEFT JOIN latest_community lcr ON lcr.entity_id = e.id
                WHERE e.merged_into IS NULL
                  AND e.tracking_tier <> 'archived'
                """
                + (
                    "AND jsonb_exists(e.attrs->'anchors', :anchor_key) "
                    if anchor_key is not None
                    else ""
                )
                + ("AND e.id = :entity_id " if entity_id is not None else "")
                + """
                ORDER BY
                  (lcr.researched_at IS NULL) DESC,
                  CASE COALESCE(ls.state, 'dormant')
                    WHEN 'breakout' THEN 0
                    WHEN 'accelerating' THEN 1
                    WHEN 'simmering' THEN 2
                    WHEN 'fading' THEN 3
                    ELSE 4
                  END,
                  e.created_at DESC,
                  e.id
                """
                + ("LIMIT :limit" if sql_limit is not None else "")
            ),
            {
                "source": source,
                "as_of": as_of,
                "as_of_day": as_of.date(),
                **({"anchor_key": anchor_key} if anchor_key is not None else {}),
                **({"limit": sql_limit} if sql_limit is not None else {}),
                **({"entity_id": entity_id} if entity_id is not None else {}),
            },
        )
        .mappings()
        .all()
    )
    targets = [_target_from_row(r) for r in rows]
    if force or entity_id is not None:
        return targets
    due = [t for t in targets if _due(t, as_of)]
    return due[:limit] if limit is not None else due


def _target_from_row(row: Any) -> CommunityTarget:
    attrs = row["attrs"] or {}
    card = row["card"] or None
    description = (attrs.get("text") or "").strip() or None
    if description is None and card:
        description = card.get("what_it_is") or card.get("function")
    anchors = attrs.get("anchors") or {}
    return CommunityTarget(
        entity_id=int(row["id"]),
        canonical_name=row["canonical_name"],
        entity_type=row["entity_type"],
        category=row["category"],
        anchors={str(k): str(v) for k, v in anchors.items()},
        owner=attrs.get("owner"),
        description=description,
        card=card,
        state=row["state"],
        last_researched_at=row["last_researched_at"],
        last_status=row["last_status"],
    )


def _due(target: CommunityTarget, as_of: datetime) -> bool:
    if target.last_researched_at is None:
        return True
    age = as_of - target.last_researched_at
    if target.last_status == "failed":
        return age >= timedelta(days=1)
    if target.last_status == "not_found":
        return age >= timedelta(days=7)
    if target.state in {"breakout", "accelerating"}:
        return age >= timedelta(days=1)
    if target.state == "simmering":
        return age >= timedelta(days=3)
    return age >= timedelta(days=14)
