"""``seismo derive-edges`` — typed entity-graph edges (Feature 1).

Pure and as-of correct, exactly like the trajectory scorers: given ``as_of`` it reads only events
attached at/before ``as_of`` and resolves every endpoint through :func:`canonical_entity_id`, so a
re-run for the same instant is idempotent. It derives three domain relations from evidence other
steps already recorded (it never fetches):

- ``built_by``  — person → repo, from a ``repo_contributors`` event's contributor logins.
- ``cited``     — repo → paper, from an arXiv id in a ``repo_readme`` event's text.
- ``depends_on``— package → package, from a ``pypi_metadata`` event's ``requires_dist`` list.

``built_by``/``cited`` mint the person/paper entity on first sight (anchored consistently with the
resolver's anchor keys); ``depends_on`` only links packages already tracked. Every edge is upserted
on ``(src, dst, edge_type)`` with the justifying raw_event id in ``evidence_refs``. Self-loops are
skipped: an R1 auto-merge can fold a cited paper into its own repo, and a repo may not cite itself.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date, datetime
from typing import Any

from sqlalchemy import func, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from seismo.db import canonical_entity_id
from seismo.identity import anchors as anchor_mod
from seismo.models import Entity, EntityGraphEdge

# Leading distribution name of a ``requires_dist`` entry ("numpy (>=1.20)" -> "numpy").
_REQ_NAME = re.compile(r"^\s*([A-Za-z0-9_.\-]+)")
# PEP 503 name normalization: runs of [-_.] collapse to a single '-', lowercased.
_PKG_SEP = re.compile(r"[-_.]+")


@dataclass
class EdgeStats:
    built_by: int = 0
    cited: int = 0
    depends_on: int = 0
    persons_created: int = 0
    papers_created: int = 0
    edges_upserted: int = 0

    def as_note(self) -> str:
        return (
            f"built_by={self.built_by} cited={self.cited} depends_on={self.depends_on} "
            f"persons+={self.persons_created} papers+={self.papers_created} "
            f"upserted={self.edges_upserted}"
        )


def _normalize_pkg(name: str) -> str:
    return _PKG_SEP.sub("-", name.strip()).lower()


def derive_edges(session: Session, as_of: datetime) -> EdgeStats:
    """Derive typed graph edges from attached evidence ≤ ``as_of``. Pure; caller commits."""
    stats = EdgeStats()
    anchor_map = _load_anchor_map(session, as_of)
    canon: dict[int, int] = {}

    def canonical(entity_id: int) -> int:
        cached = canon.get(entity_id)
        if cached is None:
            cached = canonical_entity_id(session, entity_id, as_of)
            canon[entity_id] = cached
        return cached

    _derive_built_by(session, as_of, anchor_map, canonical, stats)
    _derive_cited(session, as_of, anchor_map, canonical, stats)
    _derive_depends_on(session, as_of, canonical, stats)
    stats.edges_upserted = stats.built_by + stats.cited + stats.depends_on
    return stats


# --- shared machinery -------------------------------------------------------


def _load_anchor_map(session: Session, as_of: datetime) -> dict[str, int]:
    """``{registry:native_id -> entity_id}`` over every entity visible at ``as_of``, mirroring
    resolve.py's map. Merged losers are included; callers canonicalize after lookup, so a loser's
    anchor still resolves. As-of correct: an entity created after ``as_of`` can't anchor an edge."""
    anchor_map: dict[str, int] = {}
    rows = session.execute(
        text(
            "SELECT id, attrs->'anchors' AS anchors FROM entities"
            " WHERE attrs ? 'anchors' AND created_at <= :as_of"
        ),
        {"as_of": as_of},
    ).all()
    for entity_id, anchors in rows:
        if isinstance(anchors, dict):
            for registry, native_id in anchors.items():
                anchor_map[f"{registry}:{native_id}"] = int(entity_id)
    return anchor_map


def _attached_events(session: Session, event_type: str, as_of: datetime) -> list[Any]:
    """Attached (rule='attach') events of ``event_type`` with ``occurred_at <= as_of``."""
    return list(
        session.execute(
            text(
                """
                SELECT l.entity_id AS entity_id, r.id AS raw_id,
                       r.occurred_at AS occurred_at, r.payload AS payload
                FROM entity_links l
                JOIN raw_events r ON r.id = l.raw_event_id
                WHERE l.rule = 'attach' AND r.event_type = :etype AND r.occurred_at <= :as_of
                """
            ),
            {"etype": event_type, "as_of": as_of},
        ).mappings()
    )


def _get_or_create(
    session: Session,
    anchor_map: dict[str, int],
    registry: str,
    native_id: str,
    entity_type: str,
    display_name: str,
    created_at: datetime,
) -> tuple[int, bool]:
    """Look up an entity by its ``registry:native_id`` anchor, or create one. Returns
    ``(entity_id, created)``. New entities are born at ``created_at`` (first evidence) so the graph
    stays as-of pure, and register their anchor immediately for the rest of the run."""
    key = f"{registry}:{native_id}"
    existing = anchor_map.get(key)
    if existing is not None:
        return existing, False
    row = Entity(
        entity_type=entity_type,
        canonical_name=display_name,
        created_at=created_at,
        attrs={"anchors": {registry: native_id}},
    )
    session.add(row)
    session.flush()
    anchor_map[key] = row.id
    return row.id, True


def _upsert_edge(
    session: Session, src: int, dst: int, edge_type: str, evidence_ref: int, since: date
) -> None:
    stmt = pg_insert(EntityGraphEdge).values(
        src_entity_id=src,
        dst_entity_id=dst,
        edge_type=edge_type,
        weight=1.0,
        since=since,
        evidence_refs=[evidence_ref],
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=["src_entity_id", "dst_entity_id", "edge_type"],
        set_={
            "weight": stmt.excluded.weight,
            "evidence_refs": stmt.excluded.evidence_refs,
            "updated_at": func.now(),
        },
    )
    session.execute(stmt)


# --- built_by: person -> repo -----------------------------------------------


def _derive_built_by(
    session: Session,
    as_of: datetime,
    anchor_map: dict[str, int],
    canonical: Any,
    stats: EdgeStats,
) -> None:
    for row in _attached_events(session, "repo_contributors", as_of):
        repo_id = canonical(row["entity_id"])
        occurred: datetime = row["occurred_at"]
        for contributor in row["payload"].get("contributors") or []:
            login = contributor.get("login")
            if not login:
                continue
            person_id, created = _get_or_create(
                session, anchor_map, "github", f"user:{login}", "person", login, occurred
            )
            if created:
                stats.persons_created += 1
            person = canonical(person_id)
            if person == repo_id:
                continue  # defensive: never a self-loop
            _upsert_edge(session, person, repo_id, "built_by", row["raw_id"], occurred.date())
            stats.built_by += 1


# --- cited: repo -> paper ---------------------------------------------------


def _derive_cited(
    session: Session,
    as_of: datetime,
    anchor_map: dict[str, int],
    canonical: Any,
    stats: EdgeStats,
) -> None:
    for row in _attached_events(session, "repo_readme", as_of):
        text_body = str(row["payload"].get("text") or "")
        occurred: datetime = row["occurred_at"]
        seen: set[str] = set()
        for match in anchor_mod._ARXIV_ID.finditer(text_body):
            arxiv_id = match.group(1)
            if arxiv_id in seen:
                continue
            seen.add(arxiv_id)
            paper_id, created = _get_or_create(
                session, anchor_map, "arxiv", arxiv_id, "paper", arxiv_id, occurred
            )
            if created:
                stats.papers_created += 1
            repo = canonical(row["entity_id"])
            paper = canonical(paper_id)
            if repo == paper:
                continue  # R1 auto-merge folded the cited paper into the repo — skip self-loop
            _upsert_edge(session, repo, paper, "cited", row["raw_id"], occurred.date())
            stats.cited += 1


# --- depends_on: package -> package -----------------------------------------


def _derive_depends_on(
    session: Session, as_of: datetime, canonical: Any, stats: EdgeStats
) -> None:
    pypi_map = _pypi_lookup(session, as_of, canonical)
    for row in _attached_events(session, "pypi_metadata", as_of):
        dependent = canonical(row["entity_id"])
        occurred: datetime = row["occurred_at"]
        seen: set[str] = set()
        for entry in row["payload"].get("requires_dist") or []:
            match = _REQ_NAME.match(str(entry))
            if not match:
                continue
            dep_name = _normalize_pkg(match.group(1))
            if dep_name in seen:
                continue
            seen.add(dep_name)
            dependency = pypi_map.get(dep_name)
            if dependency is None or dependency == dependent:
                continue  # untracked package (never minted here) or self-dependency
            _upsert_edge(
                session, dependent, dependency, "depends_on", row["raw_id"], occurred.date()
            )
            stats.depends_on += 1


def _pypi_lookup(session: Session, as_of: datetime, canonical: Any) -> dict[str, int]:
    """``{normalized-pypi-name -> canonical entity id}`` for every pypi anchor visible at
    ``as_of``. As-of correct: a package entity first seen after ``as_of`` can't be a dependency
    target yet."""
    out: dict[str, int] = {}
    rows = session.execute(
        text(
            "SELECT id, attrs->'anchors'->>'pypi' AS name FROM entities "
            "WHERE attrs->'anchors' ? 'pypi' AND created_at <= :as_of"
        ),
        {"as_of": as_of},
    ).all()
    for entity_id, name in rows:
        if name:
            out[_normalize_pkg(str(name))] = canonical(int(entity_id))
    return out
