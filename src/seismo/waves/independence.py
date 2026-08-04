"""Independence checks — the half of Wave Radar that decides what is *not* a wave.

A cluster of similar young projects is only interesting if the people behind them acted
independently. Five microservices from one company, a package and its four plugins, or a fork and
its parent all look exactly like convergence to a similarity measure and are not convergence at all.
Without this filter the first wave the system ships is a false one, and a convincing false wave is
worse than silence — it teaches the reader to distrust the page.

Every check runs over the **deterministic** spine (``entity_graph_edges``, ``entities.attrs``),
never over ``entity_semantic_edges``. Model judgement decides who is *similar*; only provable
structure decides who is *independent*.

Conflicting members are **collapsed, not dropped**: when two members share a team, the earlier one
represents that team and the other is recorded as absorbed. Dropping both would let one shared
contributor delete a real wave, and dropping neither would let one team manufacture one.
"""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date, datetime

from sqlalchemy import text
from sqlalchemy.orm import Session

# Deterministic edge types that prove two entities are not independent of each other.
#   built_by / authored_by — the same humans made both
#   depends_on             — one is downstream of the other; an ecosystem, not parallel invention
_CONFLICT_VIA_PERSON = ("built_by", "authored_by")
_CONFLICT_DIRECT = ("depends_on",)


@dataclass
class ConflictReport:
    """Why two members were judged non-independent, in a form that survives into the audit row."""

    kind: str  # shared_person | dependency | shared_owner
    detail: str

    def as_dict(self) -> dict[str, str]:
        return {"kind": self.kind, "detail": self.detail}


@dataclass
class IndependenceResult:
    """Per-entity verdict. ``absorbed_into`` is set when this member represents no new team."""

    entity_id: int
    independent: bool
    absorbed_into: int | None = None
    conflicts: list[ConflictReport] = field(default_factory=list)

    def as_dict(self) -> dict[str, object]:
        return {
            "independent": self.independent,
            "absorbed_into": self.absorbed_into,
            "conflicts": [c.as_dict() for c in self.conflicts],
            "checks_run": ["shared_person", "dependency", "shared_owner"],
        }


def _shared_people(session: Session, ids: list[int], as_of: datetime) -> dict[int, set[int]]:
    """entity_id -> the person entities credited on it, as of ``as_of``.

    Both edge directions are read: ``built_by``/``authored_by`` are minted person→work in some
    derivations and work→person in others, and a one-directional read would silently miss half the
    shared-team cases — which is the failure that lets a single team's output pass as a wave."""
    rows = session.execute(
        text(
            """
            SELECT src_entity_id, dst_entity_id
            FROM entity_graph_edges
            WHERE edge_type = ANY(:types)
              AND (src_entity_id = ANY(:ids) OR dst_entity_id = ANY(:ids))
            """
        ),
        {"types": list(_CONFLICT_VIA_PERSON), "ids": ids},
    ).all()
    id_set = set(ids)
    people: dict[int, set[int]] = {i: set() for i in ids}
    for src, dst in rows:
        if src in id_set and dst not in id_set:
            people[src].add(dst)
        if dst in id_set and src not in id_set:
            people[dst].add(src)
    return people


def _dependencies(session: Session, ids: list[int], as_of: datetime) -> set[tuple[int, int]]:
    """Unordered member pairs joined by a ``depends_on`` edge in either direction."""
    rows = session.execute(
        text(
            """
            SELECT src_entity_id, dst_entity_id
            FROM entity_graph_edges
            WHERE edge_type = ANY(:types)
              AND src_entity_id = ANY(:ids) AND dst_entity_id = ANY(:ids)
            """
        ),
        {"types": list(_CONFLICT_DIRECT), "ids": ids},
    ).all()
    return {(min(s, d), max(s, d)) for s, d in rows if s != d}


def _owners(session: Session, ids: list[int]) -> dict[int, str | None]:
    """entity_id -> GitHub owner from its anchor, e.g. ``gh:acme/thing`` -> ``acme``.

    A shared owner catches the monorepo-split and product-line cases that no edge records, since
    sibling repos under one org often have no ``depends_on`` and no shared contributor yet."""
    rows = session.execute(
        text("SELECT id, attrs -> 'anchors' ->> 'github' AS gh FROM entities WHERE id = ANY(:ids)"),
        {"ids": ids},
    ).all()
    out: dict[int, str | None] = {}
    for entity_id, gh in rows:
        out[entity_id] = gh.split("/", 1)[0].lower() if gh and "/" in gh else None
    return out


def evaluate(
    session: Session,
    member_ids: list[int],
    first_seen: Mapping[int, date],
    as_of: datetime,
) -> dict[int, IndependenceResult]:
    """Collapse non-independent members, keeping the earliest-seen representative of each team.

    ``first_seen`` maps entity_id -> date and only decides *which* member represents a group, so the
    survivor is the one that actually appeared first rather than whichever the query returned first
    — otherwise the wave's ``first_seen`` would wobble between runs on unrelated ordering."""
    if not member_ids:
        return {}

    people = _shared_people(session, member_ids, as_of)
    deps = _dependencies(session, member_ids, as_of)
    owners = _owners(session, member_ids)

    # Union-find over "these two are the same team" so a chain A-B, B-C collapses to one group.
    parent = {i: i for i in member_ids}

    def find(x: int) -> int:
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a: int, b: int) -> None:
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[rb] = ra

    conflicts: dict[int, list[ConflictReport]] = {i: [] for i in member_ids}
    for idx, a in enumerate(member_ids):
        for b in member_ids[idx + 1 :]:
            shared = people[a] & people[b]
            if shared:
                note = ConflictReport("shared_person", f"person entities {sorted(shared)}")
                conflicts[a].append(note)
                conflicts[b].append(note)
                union(a, b)
            if (min(a, b), max(a, b)) in deps:
                note = ConflictReport("dependency", "depends_on edge between members")
                conflicts[a].append(note)
                conflicts[b].append(note)
                union(a, b)
            if owners[a] and owners[a] == owners[b]:
                note = ConflictReport("shared_owner", f"github owner {owners[a]!r}")
                conflicts[a].append(note)
                conflicts[b].append(note)
                union(a, b)

    groups: dict[int, list[int]] = {}
    for i in member_ids:
        groups.setdefault(find(i), []).append(i)

    results: dict[int, IndependenceResult] = {}
    for members in groups.values():
        # Earliest first_seen wins; entity id breaks ties so the choice is stable across runs.
        representative = sorted(members, key=lambda i: (first_seen[i], i))[0]
        for i in members:
            results[i] = IndependenceResult(
                entity_id=i,
                independent=(i == representative),
                absorbed_into=None if i == representative else representative,
                conflicts=conflicts[i],
            )
    return results
