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

# The anchor registry each source deep-polls. Extend as tracking collectors land (pypi, npm).
_SOURCE_REGISTRY = {"github": "github", "hf": "hf", "pypi": "pypi"}


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


def select_unenriched_targets(
    session: Session,
    source: str,
    event_type: str,
    *,
    limit: int | None = None,
    tier: str = "active",
) -> list[TrackTarget]:
    """Active, unmerged entities carrying ``source``'s anchor that do NOT yet have an enrichment
    event of ``event_type`` (e.g. ``repo_readme`` / ``model_readme``). Newest first, bounded by
    ``limit`` — so a daily run makes steady progress across the whole universe instead of
    re-fetching the same already-enriched head. This is what makes enrichment self-completing."""
    registry = _SOURCE_REGISTRY.get(source)
    if registry is None:
        return []
    sql = text(
        """
        SELECT e.id, e.attrs->'anchors'->>:registry AS native_id
        FROM entities e
        WHERE e.attrs->'anchors' ? :registry
          AND e.tracking_tier = :tier
          AND e.merged_into IS NULL
          AND NOT EXISTS (
            SELECT 1 FROM entity_links l JOIN raw_events r ON r.id = l.raw_event_id
            WHERE l.entity_id = e.id AND r.event_type = :etype)
        ORDER BY e.created_at DESC, e.id
        """
        + ("LIMIT :limit" if limit is not None else "")
    )
    params: dict[str, object] = {"registry": registry, "tier": tier, "etype": event_type}
    if limit is not None:
        params["limit"] = limit
    return [
        TrackTarget(entity_id=row.id, source=source, native_id=row.native_id)
        for row in session.execute(sql, params)
        if row.native_id
    ]


def select_carded_targets(
    session: Session, source: str, *, limit: int | None = None
) -> list[TrackTarget]:
    """Unmerged entities that carry ``source``'s anchor AND already have a comprehension card.

    The immediate-win target set for README enrichment (§16): re-enrich just the handful of repos
    that already have cards to prove the quality jump before broadening to the full universe.
    Ignores the tracking tier — a carded entity is worth enriching regardless."""
    registry = _SOURCE_REGISTRY.get(source)
    if registry is None:
        return []
    sql = text(
        """
        SELECT e.id, e.attrs->'anchors'->>:registry AS native_id
        FROM entities e
        WHERE e.attrs->'anchors' ? :registry
          AND e.merged_into IS NULL
          AND EXISTS (SELECT 1 FROM comprehension_cards c WHERE c.entity_id = e.id)
        ORDER BY e.id
        """
        + ("LIMIT :limit" if limit is not None else "")
    )
    params: dict[str, object] = {"registry": registry}
    if limit is not None:
        params["limit"] = limit
    return [
        TrackTarget(entity_id=row.id, source=source, native_id=row.native_id)
        for row in session.execute(sql, params)
        if row.native_id
    ]
