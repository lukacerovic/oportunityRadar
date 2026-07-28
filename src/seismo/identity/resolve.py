"""Entity resolution (doc 04 §1–5) — the ``seismo resolve`` engine.

Steps, in order (doc 04 §1):
1. Sweep unlinked ``raw_events``; attach each to an entity (create if unseen) via its native
   anchor (doc 04 §2). Accumulate the cross-registry references its payload declares.
2. Assign a category from accumulated text and record it in the time-versioned history; default
   its theme from the category vocabulary (doc 04 §5).
3. Run the ordered link rules R1–R6 over entity pairs (doc 04 §3): R1–R3 (reference-backed,
   conf >= 0.90) auto-merge; R4–R5 (name-backed, 0.60–0.89) queue for a human; R6 (fuzzy, <0.60)
   is recorded as an audit link only.

Everything is as-of correct: merges land in ``entity_merges`` with ``justified_at`` = the
occurred_at of the evidence, and merges/category resolve through the db.py helpers. Merges are
reversible (DR-04.2): we append to ``entity_merges`` and set the ``merged_into`` denorm, never
rewrite or delete. Re-running is idempotent — attachment dedupes on the anchor, and every
merge/queue/audit write checks for an existing row first.

``cold_start=True`` (doc 14 §8) is the one behavioral switch: R4–R6 queue items are written
with status ``deferred_coldstart`` so the high-precision R1–R3 backlog can be cleared first.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import select, text
from sqlalchemy.orm import Session

from seismo.db import canonical_entity_id
from seismo.identity import anchors as anchor_mod
from seismo.identity.normalize import normalize_name
from seismo.identity.vocab import (
    UNCATEGORIZED,
    assign_category,
    theme_for_category,
    themes,
)
from seismo.models import (
    Entity,
    EntityCategoryHistory,
    EntityLink,
    EntityMerge,
    EntityMergeQueue,
    EntityTheme,
    RawEvent,
    Theme,
)

AUTO_MERGE_BAND = 0.90
QUEUE_FLOOR = 0.60
_RULE_CONF = {"R1": 0.99, "R2": 0.97, "R3": 0.97, "R4": 0.85, "R5": 0.72, "R6": 0.55}
_TEXT_CAP = 4000  # bounded text sample kept on the entity for category (re)assignment


@dataclass
class ResolveStats:
    events_attached: int = 0
    entities_created: int = 0
    auto_merges: int = 0
    queued: int = 0
    queued_deferred: int = 0
    audit_links: int = 0
    categories_set: int = 0

    def as_note(self) -> str:
        return (
            f"attached={self.events_attached} created={self.entities_created} "
            f"merges={self.auto_merges} queued={self.queued}(+{self.queued_deferred} deferred) "
            f"audit={self.audit_links} categories={self.categories_set}"
        )


@dataclass
class _Ent:
    """In-memory working copy of an entity for the batch run."""

    id: int
    entity_type: str
    canonical_name: str
    category: str | None
    created_at: datetime
    attrs: dict[str, Any]

    @property
    def anchors(self) -> dict[str, str]:
        anchors: dict[str, str] = self.attrs.setdefault("anchors", {})
        return anchors

    @property
    def refs(self) -> list[dict[str, Any]]:
        refs: list[dict[str, Any]] = self.attrs.setdefault("references", [])
        return refs

    @property
    def norm_name(self) -> str:
        return normalize_name(self.canonical_name)


def resolve(
    session: Session, *, cold_start: bool = False, now: datetime | None = None
) -> ResolveStats:
    """Run one resolution pass over all currently-unlinked events. Returns run stats."""
    now = now or datetime.now(UTC)
    stats = ResolveStats()

    ents = _load_entities(session)
    anchor_map: dict[str, int] = {}
    for e in ents.values():
        for reg, nid in e.anchors.items():
            anchor_map[f"{reg}:{nid}"] = e.id

    _attach(session, ents, anchor_map, stats)
    _assign_categories(session, ents, now, stats)
    _apply_rules(session, ents, anchor_map, cold_start, now, stats)
    _flush_entity_attrs(session, ents)
    return stats


# --- step 1: attachment -----------------------------------------------------


def _load_entities(session: Session) -> dict[int, _Ent]:
    out: dict[int, _Ent] = {}
    for e in session.scalars(select(Entity)):
        out[e.id] = _Ent(
            id=e.id,
            entity_type=e.entity_type,
            canonical_name=e.canonical_name,
            category=e.category,
            created_at=e.created_at,
            attrs=dict(e.attrs or {}),
        )
    return out


def _unlinked_events(session: Session) -> list[RawEvent]:
    """Events with no attachment link yet. Unowned events (no anchor) never get a link, so they
    are re-examined each run and produce nothing — cheap and idempotent at v1 scale."""
    linked = select(EntityLink.raw_event_id).where(EntityLink.raw_event_id.isnot(None))
    stmt = select(RawEvent).where(RawEvent.id.notin_(linked)).order_by(RawEvent.occurred_at)
    return list(session.scalars(stmt))


def _attach(
    session: Session, ents: dict[int, _Ent], anchor_map: dict[str, int], stats: ResolveStats
) -> None:
    for event in _unlinked_events(session):
        anchor = anchor_mod.primary_anchor(event.source, event.event_type, event.payload)
        if anchor is None:
            continue  # unowned (e.g. an HN story with no registry link) — remains raw context
        ent = _find_or_create(session, ents, anchor_map, anchor, event, stats)
        # Attachment link: rule='attach', confidence 1.0, carrying the evidence occurred_at.
        session.add(
            EntityLink(
                entity_id=ent.id,
                raw_event_id=event.id,
                rule="attach",
                confidence=1.0,
                evidence_occurred_at=event.occurred_at,
            )
        )
        stats.events_attached += 1
        _absorb_payload(ent, event)
        # A seed block emits one event per anchor but all carry the block's full anchor set;
        # register the siblings so every anchor of the block resolves to this one entity.
        if event.source == "seed":
            _register_siblings(ent, anchor_map, event.payload.get("anchors") or {})
        for ref in anchor_mod.references(event.source, event.payload):
            _remember_reference(ent, ref, event.occurred_at)


def _find_or_create(
    session: Session,
    ents: dict[int, _Ent],
    anchor_map: dict[str, int],
    anchor: anchor_mod.Anchor,
    event: RawEvent,
    stats: ResolveStats,
) -> _Ent:
    existing_id = anchor_map.get(anchor.key)
    if existing_id is not None:
        return ents[existing_id]
    row = Entity(
        entity_type=anchor.entity_type,
        canonical_name=anchor.display_name,
        created_at=event.occurred_at,  # birth = first evidence, not ingest time (as-of purity)
        attrs={"anchors": {anchor.registry: anchor.native_id}},
    )
    session.add(row)
    session.flush()  # need the id
    ent = _Ent(
        row.id, anchor.entity_type, anchor.display_name, None, event.occurred_at, dict(row.attrs)
    )
    ents[ent.id] = ent
    anchor_map[anchor.key] = ent.id
    stats.entities_created += 1
    return ent


_WIKIDATA_LABEL_PROPS = {
    # claim property -> display key on the entity's attrs['wikidata'] card
    "P159": "headquarters",
    "P452": "industry",
    "P106": "occupation",
    "P166": "awards",
}


def _wikidata_card(p: dict[str, Any]) -> dict[str, Any]:
    """Compact display card from a ``wikidata_entity`` payload — what the graph node panel shows
    when a person/org node is clicked (description, website, HQ, industry, awards, dates)."""
    claims = p.get("claims") or {}

    def first_value(prop: str) -> str | None:
        for entry in claims.get(prop) or []:
            if entry.get("value"):
                return str(entry["value"])
        return None

    def first_year(prop: str) -> str | None:
        for entry in claims.get(prop) or []:
            time = str(entry.get("time") or "")
            if time:
                return time.lstrip("+")[:4]
        return None

    def year(entry: dict[str, Any], key: str) -> str:
        return str(entry.get(key) or "").lstrip("+")[:4]

    # Job titles: P39 "position held" ("CTO — OpenAI (2022–2024)") plus any role-qualified
    # P108 employments. This is where "what was their job there" lives — the employment EDGE
    # carries only the relationship; the title belongs to the person's card.
    positions: list[str] = []
    for entry in claims.get("P39") or []:
        title = entry.get("label")
        if not title:
            continue
        text = str(title)
        if entry.get("of_label"):
            text += f" — {entry['of_label']}"
        span = "–".join(s for s in (year(entry, "start"), year(entry, "end")) if s)
        if span:
            text += f" ({span})"
        positions.append(text)
    for entry in claims.get("P108") or []:
        if entry.get("role_label") and entry.get("label"):
            positions.append(f"{entry['role_label']} — {entry['label']}")

    card: dict[str, Any] = {"qid": p.get("qid"), "description": p.get("description") or None}
    if positions:
        card["positions"] = positions[:8]
    card["website"] = first_value("P856")
    card["inception"] = first_year("P571")
    card["dissolved"] = first_year("P576")
    card["employees"] = first_value("P1128")
    for prop, key in _WIKIDATA_LABEL_PROPS.items():
        labels = [str(e["label"]) for e in claims.get(prop) or [] if e.get("label")]
        if labels:
            card[key] = labels[:6]
    return {k: v for k, v in card.items() if v}


def _absorb_payload(ent: _Ent, event: RawEvent) -> None:
    """Fold an event's descriptive text + owner into the entity for category assignment."""
    p = event.payload
    if event.source == "wikidata":
        # Display card for the graph node panel — merged, so a re-fetch refreshes it.
        ent.attrs["wikidata"] = _wikidata_card(p)
        # The HF handle an org was resolved from sticks to the ENTITY: a later re-fetch of the
        # same org via the QID path carries no org_handle, and derive-edges' developed_by
        # (model → org) linkage must survive that.
        if p.get("org_handle"):
            ent.attrs["hf_org_handle"] = p["org_handle"]
    chunks = [
        str(p.get("title") or ""),
        str(p.get("description") or ""),
        str(p.get("summary") or ""),
        " ".join(str(t) for t in (p.get("topics") or [])),
        " ".join(str(t) for t in (p.get("tags") or [])),
    ]
    # An enrichment event carries deep text under `text` — a repo README (§16) or a fetched launch
    # page (Wave-3). Fold it in so build_evidence_pack's Description block (attrs['text'], truncated
    # to 4k) has real content instead of a one-line description / headline.
    enriched = event.event_type in ("repo_readme", "launch_page", "hn_discussion", "model_readme")
    if enriched and p.get("text"):
        chunks.append(str(p["text"]))
    if event.source == "seed" and p.get("category"):
        ent.attrs["seed_category"] = p["category"]
    if event.source == "seed" and p.get("themes"):
        ent.attrs["seed_themes"] = p["themes"]
    existing = ent.attrs.get("text", "")
    merged = (existing + " " + " ".join(c for c in chunks if c)).strip()
    ent.attrs["text"] = merged[:_TEXT_CAP]
    owner = _owner_of(event)
    if owner:
        ent.attrs.setdefault("owner", owner)


def _owner_of(event: RawEvent) -> str | None:
    p = event.payload
    if event.source == "github":
        full = p.get("full_name") or p.get("repo")
        if full and "/" in str(full):
            return str(full).split("/", 1)[0].lower()
    if event.source == "hf":
        mid = p.get("id") or p.get("modelId")
        if mid and "/" in str(mid):
            return str(mid).split("/", 1)[0].lower()
    if event.source == "seed":
        a = p.get("anchor") or {}
        nid = a.get("native_id") or ""
        if "/" in str(nid):
            return str(nid).split("/", 1)[0].lower()
    return None


def _register_siblings(ent: _Ent, anchor_map: dict[str, int], anchors: dict[str, str]) -> None:
    """Attach all of a seed block's registry anchors to one entity, so a later sibling event (or a
    discovered event on any of those anchors) resolves to this same entity."""
    for registry, native_id in anchors.items():
        ent.anchors.setdefault(registry, native_id)
        anchor_map.setdefault(f"{registry}:{native_id}", ent.id)


def _remember_reference(ent: _Ent, ref: anchor_mod.Reference, occurred_at: datetime) -> None:
    for existing in ent.refs:
        if existing["anchor_key"] == ref.anchor_key:
            return
    ent.refs.append(
        {
            "anchor_key": ref.anchor_key,
            "rule": ref.rule,
            "evidence": ref.evidence,
            "occurred_at": occurred_at.isoformat(),
        }
    )


# --- step 2: category + theme ----------------------------------------------


def _assign_categories(
    session: Session, ents: dict[int, _Ent], now: datetime, stats: ResolveStats
) -> None:
    for ent in ents.values():
        seed_cat = ent.attrs.get("seed_category")
        category = seed_cat if seed_cat else assign_category(ent.attrs.get("text", ""))
        if category == UNCATEGORIZED and ent.category:
            continue  # don't downgrade a real category to uncategorized on a thin later event
        if category == ent.category:
            continue
        effective = _latest_evidence(ent) or now
        session.add(
            EntityCategoryHistory(entity_id=ent.id, category=category, effective_at=effective)
        )
        ent.category = category
        stats.categories_set += 1
        _assign_theme(session, ent)


def _assign_theme(session: Session, ent: _Ent) -> None:
    theme_names = ent.attrs.get("seed_themes") or [
        theme_for_category(ent.category or UNCATEGORIZED)
    ]
    for name in theme_names:
        theme = _get_or_create_theme(session, name)
        exists = session.execute(
            select(EntityTheme).where(
                EntityTheme.entity_id == ent.id, EntityTheme.theme_id == theme.id
            )
        ).first()
        if exists:
            continue
        session.add(
            EntityTheme(
                entity_id=ent.id,
                theme_id=theme.id,
                source="seed" if ent.attrs.get("seed_themes") else "category-default",
                effective_at=_latest_evidence(ent),
            )
        )


def _get_or_create_theme(session: Session, name: str) -> Theme:
    row = session.execute(select(Theme).where(Theme.name == name)).scalar_one_or_none()
    if row is None:
        desc = themes().get(name)
        row = Theme(name=name, description=desc.description if desc else None)
        session.add(row)
        session.flush()
    return row


def _latest_evidence(ent: _Ent) -> datetime | None:
    times = [datetime.fromisoformat(r["occurred_at"]) for r in ent.refs]
    times.append(ent.created_at)
    return max(times) if times else None


# --- step 3: link rules R1–R6 ----------------------------------------------


def _apply_rules(
    session: Session,
    ents: dict[int, _Ent],
    anchor_map: dict[str, int],
    cold_start: bool,
    now: datetime,
    stats: ResolveStats,
) -> None:
    _apply_reference_rules(session, ents, anchor_map, now, stats)  # R1–R3 (auto-merge band)
    _apply_name_rules(session, ents, cold_start, now, stats)  # R4–R6 (queue / audit)


def _apply_reference_rules(
    session: Session,
    ents: dict[int, _Ent],
    anchor_map: dict[str, int],
    now: datetime,
    stats: ResolveStats,
) -> None:
    for ent in list(ents.values()):
        for ref in ent.refs:
            target_id = anchor_map.get(ref["anchor_key"])
            if target_id is None or target_id == ent.id:
                continue  # referenced thing not (yet) an entity, or self-reference
            justified = datetime.fromisoformat(ref["occurred_at"])
            if _merge_pair(
                session,
                ents,
                ent.id,
                target_id,
                ref["rule"],
                justified,
                now,
                {"rule": ref["rule"], "evidence": ref["evidence"]},
                stats,
            ):
                stats.auto_merges += 1


def _apply_name_rules(
    session: Session,
    ents: dict[int, _Ent],
    cold_start: bool,
    now: datetime,
    stats: ResolveStats,
) -> None:
    by_norm: dict[str, list[_Ent]] = {}
    for ent in ents.values():
        n = ent.norm_name
        if n:
            by_norm.setdefault(n, []).append(ent)

    handled: set[tuple[int, int]] = set()
    # R4/R5: exact normalized-name blocks (cheap, high-signal). R6: trigram over the rest.
    for group in by_norm.values():
        for i in range(len(group)):
            for j in range(i + 1, len(group)):
                a, b = group[i], group[j]
                if not _type_compatible(a, b):
                    continue
                rule = _name_rule(a, b)
                if rule is None:
                    continue
                handled.add(_pair_key(a.id, b.id))
                _record_name_candidate(session, a, b, rule, cold_start, now, stats)

    _apply_fuzzy_rule(session, ents, handled, cold_start, now, stats)


def _name_rule(a: _Ent, b: _Ent) -> str | None:
    """R4 (same owner + name) or R5 (name + creation within 30d). Names already equal here."""
    owner_a, owner_b = a.attrs.get("owner"), b.attrs.get("owner")
    if owner_a and owner_a == owner_b:
        return "R4"
    if abs((a.created_at - b.created_at).days) <= 30:
        return "R5"
    return None


def _apply_fuzzy_rule(
    session: Session,
    ents: dict[int, _Ent],
    handled: set[tuple[int, int]],
    cold_start: bool,
    now: datetime,
    stats: ResolveStats,
) -> None:
    """R6: pg_trgm similarity > 0.65 on canonical_name, type-compatible, not already paired.
    Recorded as an audit link only (<0.60 band); never queued or merged."""
    rows = session.execute(
        text(
            """
            SELECT a.id AS a_id, b.id AS b_id, similarity(a.canonical_name, b.canonical_name) AS sim
            FROM entities a
            JOIN entities b ON a.id < b.id
            WHERE a.canonical_name % b.canonical_name
              AND similarity(a.canonical_name, b.canonical_name) > 0.65
            """
        )
    ).all()
    for r in rows:
        a, b = ents.get(r.a_id), ents.get(r.b_id)
        if a is None or b is None or not _type_compatible(a, b):
            continue
        if _pair_key(a.id, b.id) in handled:
            continue
        if _audit_link_exists(session, a.id, b.id, "R6"):
            continue
        session.add(
            EntityLink(
                entity_id=a.id,
                linked_entity_id=b.id,
                rule="R6",
                confidence=_RULE_CONF["R6"],
                evidence_occurred_at=None,
            )
        )
        stats.audit_links += 1


def _record_name_candidate(
    session: Session,
    a: _Ent,
    b: _Ent,
    rule: str,
    cold_start: bool,
    now: datetime,
    stats: ResolveStats,
) -> None:
    conf = _RULE_CONF[rule]
    # canonicalize: don't queue a pair that is already merged into one entity.
    if canonical_entity_id(session, a.id, now) == canonical_entity_id(session, b.id, now):
        return
    lo, hi = sorted((a.id, b.id))
    if _queue_row_exists(session, lo, hi):
        return
    status = "deferred_coldstart" if cold_start else "pending"
    session.add(
        EntityMergeQueue(
            entity_a=lo,
            entity_b=hi,
            confidence=conf,
            evidence={
                "rule": rule,
                "name_a": a.canonical_name,
                "name_b": b.canonical_name,
                "owner_a": a.attrs.get("owner"),
                "owner_b": b.attrs.get("owner"),
                "created_a": a.created_at.isoformat(),
                "created_b": b.created_at.isoformat(),
            },
            status=status,
        )
    )
    if status == "pending":
        stats.queued += 1
    else:
        stats.queued_deferred += 1


# --- merge mechanics --------------------------------------------------------


def _merge_pair(
    session: Session,
    ents: dict[int, _Ent],
    a_id: int,
    b_id: int,
    rule: str,
    justified_at: datetime,
    now: datetime,
    evidence: dict[str, Any],
    stats: ResolveStats,
) -> bool:
    """Auto-merge two entities' canonical roots. Returns True if a new merge was written.

    Resolves both endpoints to their current canonical survivor first, so transitive references
    (paper->repo, hf->paper) collapse into one terminal entity rather than conflicting on the
    ``loser_id`` primary key. Direction: registry-anchored (non-paper) beats paper; then earliest
    ``created_at`` (doc 04 §3)."""
    root_a = canonical_entity_id(session, a_id, now)
    root_b = canonical_entity_id(session, b_id, now)
    if root_a == root_b:
        return False  # already one entity
    ea, eb = ents[root_a], ents[root_b]
    survivor, loser = (ea, eb) if _survivor_key(ea) <= _survivor_key(eb) else (eb, ea)
    session.add(
        EntityMerge(
            loser_id=loser.id,
            survivor_id=survivor.id,
            justified_at=justified_at,
            rule=rule,
            confidence=_RULE_CONF[rule],
            decided_by="auto",
            active=True,
        )
    )
    # merged_into is the convenience denorm (never read by as-of code); keep it consistent.
    session.execute(
        text("UPDATE entities SET merged_into = :s WHERE id = :l"),
        {"s": survivor.id, "l": loser.id},
    )
    session.add(
        EntityLink(
            entity_id=loser.id,
            linked_entity_id=survivor.id,
            rule=rule,
            confidence=_RULE_CONF[rule],
            evidence_occurred_at=justified_at,
        )
    )
    # Flush now so the next canonicalization sees this merge: transitive references
    # (hf->paper->repo) must collapse to one root, not re-use an already-merged loser_id.
    session.flush()
    return True


def _survivor_key(e: _Ent) -> tuple[bool, datetime, int]:
    # False (non-paper) sorts before True (paper); then earliest created; then lowest id.
    return (e.entity_type == "paper", e.created_at, e.id)


_ARTIFACT_TYPES = {"project", "model", "product"}


def _type_compatible(a: _Ent, b: _Ent) -> bool:
    """Name-based rules only pair plausibly-same types: identical types, two code/model artifacts
    (a model shipped as a repo, or a ``web`` launch that later appears as an HF model / repo of the
    same name — queued for a human), or a paper with such an artifact (papers merge into
    projects/models). An ``org`` only pairs with another ``org`` (doc 04 §6.2/§6.4)."""
    if a.entity_type == b.entity_type:
        return True
    pair = {a.entity_type, b.entity_type}
    if pair <= _ARTIFACT_TYPES:
        return True
    return "paper" in pair and bool(pair & _ARTIFACT_TYPES)


# --- idempotency probes -----------------------------------------------------


def _pair_key(a_id: int, b_id: int) -> tuple[int, int]:
    return (a_id, b_id) if a_id < b_id else (b_id, a_id)


def _queue_row_exists(session: Session, lo: int, hi: int) -> bool:
    return (
        session.execute(
            select(EntityMergeQueue.id).where(
                EntityMergeQueue.entity_a == lo, EntityMergeQueue.entity_b == hi
            )
        ).first()
        is not None
    )


def _audit_link_exists(session: Session, a_id: int, b_id: int, rule: str) -> bool:
    return (
        session.execute(
            select(EntityLink.id).where(
                EntityLink.entity_id == a_id,
                EntityLink.linked_entity_id == b_id,
                EntityLink.rule == rule,
            )
        ).first()
        is not None
    )


def _flush_entity_attrs(session: Session, ents: dict[int, _Ent]) -> None:
    """Persist accumulated anchors/text/refs/category back onto the entity rows."""
    for ent in ents.values():
        session.execute(
            text("UPDATE entities SET attrs = CAST(:a AS JSONB), category = :c WHERE id = :id"),
            {"a": _json(ent.attrs), "c": ent.category, "id": ent.id},
        )


def _json(value: dict[str, Any]) -> str:
    import json

    return json.dumps(value)
