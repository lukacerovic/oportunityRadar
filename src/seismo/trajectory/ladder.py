"""Maturity ladder detection (doc 06 §3) — rules, never inference.

Each rung is triggered by a concrete event and recorded in ``maturity_promotions`` with the
evidencing ``raw_event`` id, so every promotion is auditable. Stages are monotonic — a dead
project *fades* (a momentum state), it does not un-ship — so a reached rung is never withdrawn.
``promoted_at`` is the evidencing event's ``occurred_at`` (as-of correct, doc 13 A-2), and the
``(entity_id, stage)`` primary key makes re-running idempotent.

v1 has 3 live evidence types / 4 live rungs (doc 13 A-5): ``idea_paper`` → ``public_code`` →
``usable_artifact`` → ``distribution``. ``commercialization`` (pricing) and
``institutional_adoption`` (jobs) fire only once those collectors ship; the rules are declared
here so nothing changes in this module when they do.
"""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from seismo.db import canonical_entity_id

# The maturity ladder, low → high (doc 06 §3). Monotonic; the canonical vocabulary for both the
# ladder detector here and the comprehension card's ``maturity_stage`` field (doc 05 §1).
MATURITY_STAGES: tuple[str, ...] = (
    "idea_paper",
    "public_code",
    "usable_artifact",
    "distribution",
    "commercialization",
    "institutional_adoption",
)

INSTITUTIONAL_WINDOW_DAYS = 90
INSTITUTIONAL_MIN_ORGS = 3
# API-launch keywords that promote a release/changelog to commercialization (versioned list).
COMMERCIALIZATION_KEYWORDS = (
    "pricing",
    "api access",
    "generally available",
    "ga release",
    "paid tier",
)


@dataclass
class _StreamEvent:
    event_id: int
    source: str
    event_type: str
    occurred_at: datetime
    payload: dict[str, Any]


@dataclass
class LadderStats:
    promotions: int = 0
    per_stage: dict[str, int] | None = None

    def as_note(self) -> str:
        per = " ".join(f"{k}={v}" for k, v in sorted((self.per_stage or {}).items()))
        return f"promotions={self.promotions} [{per}]"


def run_ladder(session: Session, as_of: datetime) -> LadderStats:
    """Detect every maturity rung reached by ``as_of`` and record new promotions."""
    streams = _streams(session, as_of)
    existing = _existing_promotions(session)
    stats = LadderStats(per_stage={})
    for entity_id, evs in streams.items():
        for stage, promoted_at, event_id in _detect(evs):
            if (entity_id, stage) in existing:
                continue
            session.execute(
                text(
                    """
                    INSERT INTO maturity_promotions (entity_id, stage, promoted_at, evidence_event)
                    VALUES (:e, :s, :t, :ev)
                    ON CONFLICT (entity_id, stage) DO NOTHING
                    """
                ),
                {"e": entity_id, "s": stage, "t": promoted_at, "ev": event_id},
            )
            existing.add((entity_id, stage))
            stats.promotions += 1
            assert stats.per_stage is not None
            stats.per_stage[stage] = stats.per_stage.get(stage, 0) + 1
    return stats


def _detect(evs: list[_StreamEvent]) -> list[tuple[str, datetime, int]]:
    """Return ``(stage, promoted_at, evidence_event)`` for every rung this entity's events trigger.
    Each rung is independent — a repo with no paper starts at ``public_code`` — and evidenced by
    the *earliest* qualifying event."""
    found: list[tuple[str, datetime, int]] = []
    rules: dict[str, Callable[[_StreamEvent], bool]] = {
        "idea_paper": lambda e: e.source == "arxiv" or e.event_type == "paper_published",
        "public_code": lambda e: e.source == "github",
        "usable_artifact": lambda e: e.event_type == "release_published" or e.source == "hf",
        "distribution": lambda e: e.source in ("pypi", "npm"),
        "commercialization": _is_commercialization,
    }
    for stage, predicate in rules.items():
        hit = _earliest(evs, predicate)
        if hit is not None:
            found.append((stage, hit.occurred_at, hit.event_id))
    inst = _institutional(evs)
    if inst is not None:
        found.append(inst)
    return found


def _earliest(
    evs: list[_StreamEvent], predicate: Callable[[_StreamEvent], bool]
) -> _StreamEvent | None:
    hits = [e for e in evs if predicate(e)]
    return min(hits, key=lambda e: e.occurred_at) if hits else None


def _is_commercialization(e: _StreamEvent) -> bool:
    if e.source == "pricing" and e.event_type == "page_changed":
        return True
    if e.event_type in ("release_published", "changelog"):
        text_blob = " ".join(
            str(e.payload.get(k) or "") for k in ("title", "body", "description", "summary")
        ).lower()
        return any(kw in text_blob for kw in COMMERCIALIZATION_KEYWORDS)
    return False


def _institutional(evs: list[_StreamEvent]) -> tuple[str, datetime, int] | None:
    """≥3 ``job_mention`` events from distinct orgs within any 90-day window."""
    jobs = sorted((e for e in evs if e.event_type == "job_mention"), key=lambda e: e.occurred_at)
    for i, anchor in enumerate(jobs):
        window_end = anchor.occurred_at + timedelta(days=INSTITUTIONAL_WINDOW_DAYS)
        orgs: dict[str, _StreamEvent] = {}
        for e in jobs[i:]:
            if e.occurred_at > window_end:
                break
            org = str(e.payload.get("org") or e.payload.get("company") or "").lower()
            if org:
                orgs.setdefault(org, e)
            if len(orgs) >= INSTITUTIONAL_MIN_ORGS:
                trigger = max(orgs.values(), key=lambda e: e.occurred_at)
                return ("institutional_adoption", trigger.occurred_at, trigger.event_id)
    return None


def _streams(session: Session, as_of: datetime) -> dict[int, list[_StreamEvent]]:
    rows = session.execute(
        text(
            """
            SELECT l.entity_id AS entity_id, r.id AS event_id, r.source AS source,
                   r.event_type AS event_type, r.occurred_at AS occurred_at, r.payload AS payload
            FROM entity_links l
            JOIN raw_events r ON r.id = l.raw_event_id
            WHERE l.rule = 'attach' AND r.occurred_at <= :as_of
            ORDER BY r.occurred_at
            """
        ),
        {"as_of": as_of},
    ).mappings()
    canonical: dict[int, int] = {}
    streams: dict[int, list[_StreamEvent]] = {}
    for row in rows:
        raw_id = row["entity_id"]
        if raw_id not in canonical:
            canonical[raw_id] = canonical_entity_id(session, raw_id, as_of)
        streams.setdefault(canonical[raw_id], []).append(
            _StreamEvent(
                event_id=row["event_id"],
                source=row["source"],
                event_type=row["event_type"],
                occurred_at=row["occurred_at"],
                payload=row["payload"] or {},
            )
        )
    return streams


def _existing_promotions(session: Session) -> set[tuple[int, str]]:
    return {
        (e, s)
        for e, s in session.execute(text("SELECT entity_id, stage FROM maturity_promotions")).all()
    }
