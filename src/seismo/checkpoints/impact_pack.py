"""Impact-brief input pack (doc 08 §3) — the *only* thing the impact-checkpoint prompt ever sees.

Like the comprehension pack (doc 05 §2) this is pure, deterministic, bounded and versioned
(``BRIEF_PACK_VERSION``): same entity + ``as_of`` → same markdown, so a brief is reproducible and a
pack-builder change is auditable. It assembles four sections (doc 08 §3):

1. the latest *ok* comprehension card (what the entity is — checkpoint 1's structured output),
2. a momentum summary (state history, promotions, velocity percentile),
3. **only the exposure-map slices whose ``reach_links`` match this entity's category** — never the
   whole map; the model reasons over a pre-selected surface, and
4. the mechanism taxonomy verbatim (idea-spec §7), so the brief names transmissions from a closed set.

Every read is as-of correct (canonical entity + ``occurred_at <= as_of``), so a hindcast brief sees
only what was knowable then. The builder also returns the :class:`CategoryReach` it selected, so the
orchestrator can post-validate ticker exposures against the exact slices the model was shown.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from seismo.db import canonical_entity_id, category_asof
from seismo.significance.exposure import CategoryReach, category_reach

BRIEF_PACK_VERSION = 1

_PACK_CAP = 48000  # ~12k-token hard ceiling, same discipline as the comprehension pack

# idea-spec §7, verbatim. In the pack so the model names mechanisms from the closed taxonomy and
# nothing else — the schema enum enforces it, this explains what each one means.
MECHANISM_TAXONOMY = (
    "# Mechanism taxonomy (name at least one; use only these)\n"
    "- substitution — a cheaper or better replacement for something people currently pay for.\n"
    "- cost_collapse — an input cost drops sharply, eroding a margin or a moat.\n"
    "- commoditization — a differentiated layer becomes open or standard; value migrates up or "
    "down the stack.\n"
    "- enablement — a new capability makes previously non-viable use cases viable, creating demand "
    "somewhere else in the chain.\n"
    "- dependency_risk — an entity becomes load-bearing for many others; its failure, capture, or "
    "repricing propagates."
)


@dataclass
class BriefPack:
    entity_id: int  # canonical
    entity_ref: str
    markdown: str
    card: dict[str, Any]  # latest ok comprehension card body (checkpoint 1)
    category: str | None
    reach: CategoryReach  # the matched map surface, for post-validation
    event_ids: list[int]  # raw_event ids in the pack, the brief's evidence_refs vocabulary


def build_brief_pack(session: Session, entity_id: int, as_of: datetime) -> BriefPack:
    canonical = canonical_entity_id(session, entity_id, as_of)
    ent = (
        session.execute(
            text("SELECT entity_type, canonical_name FROM entities WHERE id = :id"),
            {"id": canonical},
        )
        .mappings()
        .one()
    )
    category = category_asof(session, canonical, as_of)
    card = _latest_card(session, canonical, as_of)
    momentum = _momentum(session, canonical, as_of)
    promotions = _promotions(session, canonical, as_of)
    event_ids = _event_ids(session, canonical, as_of)
    reach = category_reach(session, category)

    parts = [
        _header(ent["canonical_name"], ent["entity_type"], category),
        _card_block(card),
        _momentum_block(momentum, promotions),
        _map_block(reach),
        MECHANISM_TAXONOMY,
    ]
    markdown = "\n\n".join(p for p in parts if p).strip()[:_PACK_CAP]
    return BriefPack(
        entity_id=canonical,
        entity_ref=ent["canonical_name"],
        markdown=markdown,
        card=card,
        category=category,
        reach=reach,
        event_ids=event_ids,
    )


def _header(name: str, etype: str, category: str | None) -> str:
    return (
        "# Entity\n"
        f"- name: {name}\n"
        f"- type: {etype}\n"
        f"- category: {category or 'uncategorized'}"
    )


def _card_block(card: dict[str, Any]) -> str:
    if not card:
        return "# Comprehension card\n(none available)"
    lines = ["# Comprehension card (checkpoint 1 — what this entity is)"]
    for key in (
        "what_it_is",
        "function",
        "claimed_advantage",
        "maturity_stage",
        "who_is_behind",
        "confidence",
    ):
        val = card.get(key)
        if val:
            lines.append(f"- {key}: {val}")
    for key in ("replaces_or_enables", "open_questions"):
        vals = card.get(key) or []
        if vals:
            lines.append(f"- {key}: {'; '.join(str(v) for v in vals)}")
    return "\n".join(lines)


def _momentum_block(momentum: list[Any], promotions: list[Any]) -> str:
    lines = ["# Momentum summary"]
    if momentum:
        latest = momentum[0]
        inputs = latest["inputs"] or {}
        p = inputs.get("P")
        lines.append(
            f"- current state: {latest['state']}"
            + (f" (velocity percentile P={p:.2f})" if isinstance(p, (int, float)) else "")
        )
        recent = ", ".join(f"{r['day'].isoformat()}:{r['state']}" for r in momentum[:6])
        lines.append(f"- recent states: {recent}")
    else:
        lines.append("- current state: dormant (no momentum history)")
    if promotions:
        rungs = ", ".join(f"{p['stage']}@{p['promoted_at'].date().isoformat()}" for p in promotions)
        lines.append(f"- maturity promotions: {rungs}")
    return "\n".join(lines)


def _map_block(reach: CategoryReach) -> str:
    if reach.is_empty:
        return (
            "# Exposure-map surface\n"
            "(no mapped companies for this category — you should not have been asked to brief this)"
        )
    lines = [
        "# Exposure-map surface (ONLY the companies this category touches — reason over these)",
        "Each threat entry is (relation, core). Resolve ticker exposures to these revenue lines.",
    ]
    for cs in reach.slices:
        lines.append(f"\n## {cs.ticker} — {cs.name} ({cs.sector})")
        for ln in cs.lines:
            threats = ", ".join(f"{rel}{'*core' if core else ''}" for rel, core in ln.threats)
            lines.append(
                f"- revenue_line `{ln.id}` ({ln.name}, ~{ln.share_of_revenue:.0%} of revenue): "
                f"{threats}"
            )
        if cs.moat_notes:
            lines.append(f"  moat: {cs.moat_notes.strip()}")
        if cs.sensitivity_notes:
            lines.append(f"  sensitivity: {cs.sensitivity_notes.strip()}")
    return "\n".join(lines)


def _latest_card(session: Session, canonical: int, as_of: datetime) -> dict[str, Any]:
    row = session.execute(
        text(
            "SELECT card FROM comprehension_cards WHERE entity_id = :id AND as_of <= :as_of "
            "AND status = 'ok' ORDER BY version DESC LIMIT 1"
        ),
        {"id": canonical, "as_of": as_of},
    ).scalar()
    return dict(row) if row else {}


def _momentum(session: Session, canonical: int, as_of: datetime) -> list[Any]:
    return list(
        session.execute(
            text(
                "SELECT day, state, inputs FROM momentum_states WHERE entity_id = :id "
                "AND day <= :d ORDER BY day DESC LIMIT 30"
            ),
            {"id": canonical, "d": as_of.date()},
        ).mappings()
    )


def _promotions(session: Session, canonical: int, as_of: datetime) -> list[Any]:
    return list(
        session.execute(
            text(
                "SELECT stage, promoted_at FROM maturity_promotions WHERE entity_id = :id "
                "AND promoted_at <= :as_of ORDER BY promoted_at"
            ),
            {"id": canonical, "as_of": as_of},
        ).mappings()
    )


def _event_ids(session: Session, canonical: int, as_of: datetime) -> list[int]:
    rows = session.execute(
        text(
            "SELECT r.id FROM entity_links l JOIN raw_events r ON r.id = l.raw_event_id "
            "WHERE l.entity_id = :id AND l.rule = 'attach' AND r.occurred_at <= :as_of "
            "ORDER BY r.occurred_at DESC LIMIT 40"
        ),
        {"id": canonical, "as_of": as_of},
    ).scalars()
    return [int(r) for r in rows]
