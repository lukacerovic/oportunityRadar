"""Track-target selection (doc 03 DR-03.3) — which known entities get deep-polled each day.

Discovery finds new things; *tracking* re-observes known ones to build the metric time series the
trajectory layer needs (``repo_snapshot`` → ``gh_stars`` velocity). Targets are the canonical
survivors that carry a registry anchor and are still on the ``active`` tracking tier (A-4 bounds
the set; a ``slow``/``archived`` entity is polled rarely or not at all). Merged losers are excluded
— their evidence already folds onto the survivor.
"""

from __future__ import annotations

from sqlalchemy import text
from sqlalchemy.orm import Session

from seismo.collectors.base import TrackTarget

# The anchor registry each source deep-polls. Extend as tracking collectors land (hf, pypi, npm).
_SOURCE_REGISTRY = {"github": "github"}


def select_targets(
    session: Session, source: str, *, tier: str = "active", limit: int | None = None
) -> list[TrackTarget]:
    """Active, unmerged entities that carry ``source``'s anchor, as ``TrackTarget``s.

    Ordered by id for a stable poll order. ``limit`` caps the set (testing/rate budget)."""
    registry = _SOURCE_REGISTRY.get(source)
    if registry is None:
        return []
    sql = text(
        """
        SELECT id, attrs->'anchors'->>:registry AS native_id
        FROM entities
        WHERE attrs->'anchors' ? :registry
          AND tracking_tier = :tier
          AND merged_into IS NULL
        ORDER BY id
        """
        + ("LIMIT :limit" if limit is not None else "")
    )
    params: dict[str, object] = {"registry": registry, "tier": tier}
    if limit is not None:
        params["limit"] = limit
    return [
        TrackTarget(entity_id=row.id, source=source, native_id=row.native_id)
        for row in session.execute(sql, params)
        if row.native_id
    ]
