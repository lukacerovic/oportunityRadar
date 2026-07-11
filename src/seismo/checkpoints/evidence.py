"""Evidence-pack assembly (doc 05 §2) — the *only* thing the comprehension prompt ever sees.

``build_evidence_pack`` is pure, deterministic, bounded, and versioned (``PACK_VERSION``): the same
entity + ``as_of`` always yields the same markdown, so a card is reproducible and a pack-builder
change is auditable (doc 05 §2/§6). Nothing outside the pack reaches the model — no live browsing,
no world knowledge — which is what keeps a card grounded and its claims traceable to raw events.

Every read is as-of correct: events resolve to the canonical entity at ``as_of`` and only
``occurred_at <= as_of`` is visible, so a hindcast pack contains only what was knowable then.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from seismo.db import canonical_entity_id, category_asof

PACK_VERSION = 1

_TEXT_CAP = 4000  # per doc 05 §2: README/abstract truncated to first 4k chars
_PACK_CAP = 48000  # ~12k-token hard ceiling (doc 05 §2)
_TIMELINE_CAP = 40  # most-recent events summarised in the timeline


@dataclass
class EvidencePack:
    entity_id: int  # canonical
    markdown: str
    event_ids: list[int]  # raw_event ids referenced, for the card's evidence_refs vocabulary
    rule_category: str | None  # the deterministic category, to detect model disagreement


def build_evidence_pack(session: Session, entity_id: int, as_of: datetime) -> EvidencePack:
    canonical = canonical_entity_id(session, entity_id, as_of)
    ent = (
        session.execute(
            text(
                "SELECT entity_type, canonical_name, attrs, created_at FROM entities WHERE id = :id"
            ),
            {"id": canonical},
        )
        .mappings()
        .one()
    )
    rule_category = category_asof(session, canonical, as_of)
    events = _events(session, canonical, as_of)
    metrics = _latest_metrics(session, canonical, as_of)
    promotions = _promotions(session, canonical, as_of)

    attrs = ent["attrs"] or {}
    parts: list[str] = []
    parts.append(_identity_header(ent, rule_category, attrs))
    parts.append(_description(attrs))
    parts.append(_timeline(events, promotions))
    parts.append(_metrics_block(metrics))
    markdown = "\n\n".join(p for p in parts if p).strip()[:_PACK_CAP]

    return EvidencePack(
        entity_id=canonical,
        markdown=markdown,
        event_ids=[e["id"] for e in events],
        rule_category=rule_category,
    )


def _identity_header(ent: Any, rule_category: str | None, attrs: dict[str, Any]) -> str:
    anchors = attrs.get("anchors") or {}
    anchor_line = ", ".join(f"{reg}:{nid}" for reg, nid in sorted(anchors.items())) or "none"
    owner = attrs.get("owner") or "unknown"
    return (
        "# Identity\n"
        f"- name: {ent['canonical_name']}\n"
        f"- type: {ent['entity_type']}\n"
        f"- rule_category: {rule_category or 'uncategorized'}\n"
        f"- owner: {owner}\n"
        f"- registries: {anchor_line}\n"
        f"- first_seen: {ent['created_at'].date().isoformat()}"
    )


def _description(attrs: dict[str, Any]) -> str:
    body = (attrs.get("text") or "").strip()
    if not body:
        return ""
    return "# Description (README / abstract, truncated)\n" + body[:_TEXT_CAP]


def _timeline(events: list[Any], promotions: list[Any]) -> str:
    lines: list[str] = ["# Event timeline (most recent first)"]
    for p in promotions:
        lines.append(f"- {p['promoted_at'].date().isoformat()} maturity → {p['stage']}")
    for e in events[:_TIMELINE_CAP]:
        payload = e["payload"] or {}
        title = str(payload.get("title") or payload.get("full_name") or payload.get("id") or "")
        extra = ""
        if e["source"] == "hn" and payload.get("points") is not None:
            extra = f" ({payload['points']} pts)"
        lines.append(
            f"- [event {e['id']}] {e['occurred_at'].date().isoformat()} "
            f"{e['source']}/{e['event_type']}: {title[:160]}{extra}"
        )
    if len(events) > _TIMELINE_CAP:
        lines.append(f"- … {len(events) - _TIMELINE_CAP} earlier events omitted")
    return "\n".join(lines)


def _metrics_block(metrics: list[Any]) -> str:
    if not metrics:
        return ""
    lines = ["# Latest metric snapshots"]
    for m in metrics:
        lines.append(f"- {m['metric']}: {m['value']} (as of {m['day'].isoformat()})")
    return "\n".join(lines)


def _events(session: Session, canonical: int, as_of: datetime) -> list[Any]:
    """Attached events for the canonical entity and every loser that merged into it (as of
    ``as_of``), newest first. The recursive CTE walks ``entity_merges`` *backwards* from the
    survivor — the inverse of :func:`canonical_entity_id` — so a merged loser's events fold in."""
    rows = session.execute(
        text(
            """
            WITH RECURSIVE members AS (
                SELECT CAST(:cid AS BIGINT) AS id
                UNION
                SELECT m.loser_id
                FROM entity_merges m
                JOIN members ON m.survivor_id = members.id
                WHERE m.active AND m.justified_at <= :as_of
            )
            SELECT r.id AS id, r.source AS source, r.event_type AS event_type,
                   r.occurred_at AS occurred_at, r.payload AS payload
            FROM entity_links l
            JOIN raw_events r ON r.id = l.raw_event_id
            WHERE l.rule = 'attach' AND r.occurred_at <= :as_of
              AND l.entity_id IN (SELECT id FROM members)
            ORDER BY r.occurred_at DESC
            """
        ),
        {"as_of": as_of, "cid": canonical},
    ).mappings()
    return list(rows)


def _latest_metrics(session: Session, canonical: int, as_of: datetime) -> list[Any]:
    return list(
        session.execute(
            text(
                """
                SELECT DISTINCT ON (metric) metric, day, value
                FROM entity_metrics_daily
                WHERE entity_id = :cid AND day <= :as_of_day
                ORDER BY metric, day DESC
                """
            ),
            {"cid": canonical, "as_of_day": as_of.date()},
        ).mappings()
    )


def _promotions(session: Session, canonical: int, as_of: datetime) -> list[Any]:
    return list(
        session.execute(
            text(
                """
                SELECT stage, promoted_at FROM maturity_promotions
                WHERE entity_id = :cid AND promoted_at <= :as_of
                ORDER BY promoted_at DESC
                """
            ),
            {"cid": canonical, "as_of": as_of},
        ).mappings()
    )
