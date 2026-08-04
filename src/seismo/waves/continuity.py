"""Wave identity across runs — the problem the detection algorithm hides.

Detection recomputes clusters from scratch on every run, and member sets shift as new entities land.
Minting a new wave id each day would make ``first_seen`` reset constantly, turn the waves page into
churn instead of a story, and destroy the only thing this product ultimately sells: a dated record
that was written before the outcome was known.

Rule: today's cluster is matched to the existing wave it overlaps most. At or above
``wave_continuity_overlap`` (measured against the *smaller* set, so a growing wave still matches its
earlier, smaller self) it **is** that wave — same id, same ``first_seen``, new members appended with
their own ``joined_at``. Otherwise a new wave is minted.

Append-only, like everything else here: members are never deleted, a wave that goes quiet is not
dissolved, and a wave absorbed into another is marked ``merged_into`` rather than removed.
"""

from __future__ import annotations

import json
from datetime import date, datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from seismo.config import settings


def _existing_waves(session: Session) -> dict[int, set[int]]:
    """Live wave id -> its current member ids. Merged-away waves are excluded so a cluster can't
    match into a wave that has already been absorbed by another."""
    rows = session.execute(
        text(
            """
            SELECT m.wave_id, m.entity_id
            FROM wave_members m
            JOIN wave_clusters w ON w.id = m.wave_id
            WHERE w.merged_into IS NULL
            """
        )
    ).all()
    out: dict[int, set[int]] = {}
    for wave_id, entity_id in rows:
        out.setdefault(wave_id, set()).add(entity_id)
    return out


def match_wave(members: set[int], existing: dict[int, set[int]]) -> int | None:
    """The best-overlapping existing wave, or ``None`` to mint a new one.

    Overlap is normalized by the smaller set on purpose. Normalizing by the union would make a wave
    that doubles in size fail to match itself, which is exactly when continuity matters most."""
    best_id, best_overlap = None, 0.0
    for wave_id, existing_members in existing.items():
        shared = len(members & existing_members)
        if not shared:
            continue
        overlap = shared / max(1, min(len(members), len(existing_members)))
        # Ties break on the lower id: the older wave wins, so identity drifts toward the original.
        if overlap > best_overlap or (overlap == best_overlap and best_id and wave_id < best_id):
            best_id, best_overlap = wave_id, overlap
    if best_id is not None and best_overlap >= settings.wave_continuity_overlap:
        return best_id
    return None


def persist_wave(
    session: Session,
    *,
    member_ids: list[int],
    first_seen: dict[int, date],
    link_reasons: dict[int, dict[str, Any]],
    independence: dict[int, dict[str, Any]],
    strength: float,
    components: dict[str, Any],
    as_of: datetime,
) -> tuple[int, bool]:
    """Write a detected cluster as a wave. Returns ``(wave_id, created_new)``."""
    members = set(member_ids)
    existing = _existing_waves(session)
    wave_id = match_wave(members, existing)
    created = wave_id is None

    earliest = min(first_seen.values())
    latest = max(first_seen.values())

    if created:
        new_id: int = session.execute(
            text(
                """
                INSERT INTO wave_clusters
                  (first_seen, last_active, window_days, strength, components, as_of)
                VALUES (:first_seen, :last_active, :window_days, :strength,
                        CAST(:components AS jsonb), :as_of)
                RETURNING id
                """
            ),
            {
                "first_seen": earliest,
                "last_active": latest,
                "window_days": settings.wave_window_days,
                "strength": strength,
                "components": json.dumps(components),
                "as_of": as_of,
            },
        ).scalar_one()
        wave_id = new_id
    else:
        # first_seen is deliberately NOT updated — it is the wave's birth date and the whole point
        # of the record. Only recomputed facts move.
        session.execute(
            text(
                """
                UPDATE wave_clusters
                SET last_active = GREATEST(last_active, :last_active),
                    strength = :strength,
                    components = CAST(:components AS jsonb),
                    as_of = :as_of,
                    updated_at = now()
                WHERE id = :id
                """
            ),
            {
                "last_active": latest,
                "strength": strength,
                "components": json.dumps(components),
                "as_of": as_of,
                "id": wave_id,
            },
        )

    for entity_id in sorted(members):
        session.execute(
            text(
                """
                INSERT INTO wave_members
                  (wave_id, entity_id, joined_at, link_reason, independence)
                VALUES (:wave_id, :entity_id, :joined_at, CAST(:link_reason AS jsonb),
                        CAST(:independence AS jsonb))
                ON CONFLICT (wave_id, entity_id) DO UPDATE
                  SET link_reason = EXCLUDED.link_reason,
                      independence = EXCLUDED.independence
                """
            ),
            {
                "wave_id": wave_id,
                "entity_id": entity_id,
                # joined_at is the member's own first evidence, so a member added on a later run
                # still records when it actually appeared, not when we noticed it.
                "joined_at": first_seen[entity_id],
                "link_reason": json.dumps(link_reasons.get(entity_id, {})),
                "independence": json.dumps(independence.get(entity_id, {})),
            },
        )
    assert wave_id is not None  # set on both branches above
    return int(wave_id), created
