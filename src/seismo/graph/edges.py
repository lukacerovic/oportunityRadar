"""``seismo derive-edges`` — typed entity-graph edges (Feature 1).

Pure and as-of correct, exactly like the trajectory scorers: given ``as_of`` it reads only events
attached at/before ``as_of`` and resolves every endpoint through :func:`canonical_entity_id`, so a
re-run for the same instant is idempotent. It derives three domain relations from evidence other
steps already recorded (it never fetches):

- ``built_by``   — person → repo, from a ``repo_contributors`` event's contributor logins.
- ``cited``      — repo → paper, from an arXiv id in a ``repo_readme`` event's text.
- ``depends_on`` — package → package, from a ``pypi_metadata`` event's ``requires_dist`` list.
- ``authored_by``— paper → person, from a ``paper_published`` event's ``authors`` name list.
- ``employed_by``/``formerly_at`` — person → org, from a ``wikidata_entity`` event's P108
  employer claims (an end-date qualifier makes it ``formerly_at``).
- ``founded``    — person → org, from an org ``wikidata_entity`` event's P112 claims (inverted);
  P169 (CEO) / P1037 (director) / P488 (chair) / P3320 (board) targets land as ``employed_by``.
- ``developed_by`` — model → org, when an org ``wikidata_entity`` event carries the HF
  ``org_handle`` it was resolved from: every tracked model under that handle links to the org.
- ``educated_at`` — person → org, from P69; ``advised_by`` — person → person, from P184
  (doctoral advisor) and P185 (doctoral student, inverted) — academic lineage.
- ``notable_work`` — person → work, from P800: what a founder/researcher is famous for
  building (ChatGPT, TensorFlow, a landmark paper). Targets mint as ``work`` entities.
- ``subsidiary_of`` — org → parent org, from P749 (and P355 inverted); ``owned_by`` — org →
  owner, from P127; ``invested_in`` — backer → org, from P1951 (inverted) — who controls and
  funds the org behind a project.

``built_by``/``cited``/``authored_by`` mint the person/paper entity on first sight (anchored
consistently with the resolver's anchor keys); ``depends_on`` only links packages already tracked.
Authors are anchored ``person_name:<slug>`` — a deliberately weak identity (names collide); a
later Wikidata QID anchor becomes the strong one and duplicates fold via the merge machinery.
Every edge is upserted
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
    authored_by: int = 0
    employed_by: int = 0
    formerly_at: int = 0
    founded: int = 0
    developed_by: int = 0
    educated_at: int = 0
    advised_by: int = 0
    subsidiary_of: int = 0
    owned_by: int = 0
    invested_in: int = 0
    notable_work: int = 0
    persons_created: int = 0
    papers_created: int = 0
    orgs_created: int = 0
    works_created: int = 0
    edges_upserted: int = 0

    def as_note(self) -> str:
        return (
            f"built_by={self.built_by} cited={self.cited} depends_on={self.depends_on} "
            f"authored_by={self.authored_by} employed_by={self.employed_by} "
            f"formerly_at={self.formerly_at} founded={self.founded} "
            f"developed_by={self.developed_by} educated_at={self.educated_at} "
            f"advised_by={self.advised_by} subsidiary_of={self.subsidiary_of} "
            f"owned_by={self.owned_by} invested_in={self.invested_in} "
            f"notable_work={self.notable_work} "
            f"persons+={self.persons_created} papers+={self.papers_created} "
            f"orgs+={self.orgs_created} works+={self.works_created} "
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
    _derive_authored_by(session, as_of, anchor_map, canonical, stats)
    _derive_affiliations(session, as_of, anchor_map, canonical, stats)
    stats.edges_upserted = (
        stats.built_by + stats.cited + stats.depends_on + stats.authored_by
        + stats.employed_by + stats.formerly_at + stats.founded + stats.developed_by
        + stats.educated_at + stats.advised_by + stats.subsidiary_of
        + stats.owned_by + stats.invested_in + stats.notable_work
    )
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


# --- authored_by: paper -> person --------------------------------------------


def _derive_authored_by(
    session: Session,
    as_of: datetime,
    anchor_map: dict[str, int],
    canonical: Any,
    stats: EdgeStats,
) -> None:
    for row in _attached_events(session, "paper_published", as_of):
        paper_id = canonical(row["entity_id"])
        occurred: datetime = row["occurred_at"]
        seen: set[str] = set()
        for name in row["payload"].get("authors") or []:
            display = str(name).strip()
            slug = anchor_mod._slugify(display)
            if not slug or slug in seen:
                continue
            seen.add(slug)
            person_id, created = _get_or_create(
                session, anchor_map, "person_name", slug, "person", display, occurred
            )
            if created:
                stats.persons_created += 1
            person = canonical(person_id)
            if person == paper_id:
                continue  # defensive: never a self-loop
            _upsert_edge(session, paper_id, person, "authored_by", row["raw_id"], occurred.date())
            stats.authored_by += 1


# --- team: person <-> org from wikidata_entity claims ------------------------


def _derive_affiliations(
    session: Session,
    as_of: datetime,
    anchor_map: dict[str, int],
    canonical: Any,
    stats: EdgeStats,
) -> None:
    """Team edges from Wikidata claims (WIKIDATA_ENRICHMENT_PLAN.md Phase 3).

    A person event's P108 employer claims become ``employed_by`` (no end date) or ``formerly_at``
    (P582 end qualifier present). An org event's P112 founded-by claims become ``founded``
    (person → org, inverted); its P169/P1037 (CEO/director) targets land as ``employed_by``.
    Claim targets are minted on first sight, anchored ``wikidata:<QID>`` — labels were embedded
    at fetch time (pruned claims), so nothing here touches the network."""
    def mint(entry: dict[str, Any], entity_type: str, occurred: datetime) -> int | None:
        qid = entry.get("qid")
        if not qid:
            return None
        counter = {
            "org": "orgs_created",
            "person": "persons_created",
            "work": "works_created",
        }[entity_type]
        entity_id, created = _get_or_create(
            session,
            anchor_map,
            "wikidata",
            str(qid),
            entity_type,
            str(entry.get("label") or qid),
            occurred,
        )
        if created:
            setattr(stats, counter, getattr(stats, counter) + 1)
        return canonical(entity_id)

    org_props = (
        ("P112", "founded"),
        ("P169", "employed_by"),  # CEO
        ("P1037", "employed_by"),  # director / manager
        ("P488", "employed_by"),  # chairperson
        ("P3320", "employed_by"),  # board member
    )
    for row in _attached_events(session, "wikidata_entity", as_of):
        subject = canonical(row["entity_id"])
        occurred: datetime = row["occurred_at"]
        payload = row["payload"]
        claims = payload.get("claims") or {}
        seen: set[tuple[str, str]] = set()

        def link(
            entry: dict[str, Any],
            edge_type: str,
            target_type: str,
            *,
            outgoing: bool,
            # bound per-iteration via defaults so the closure doesn't lazily capture loop vars
            subject: int = subject,
            occurred: datetime = occurred,
            seen: set = seen,
            raw_id: int = row["raw_id"],
        ) -> None:
            """Mint the claim target and upsert one edge. ``outgoing``: subject → target
            (employed_by, subsidiary_of, owned_by); else target → subject (founded, invested_in)."""
            key = (edge_type, str(entry.get("qid")), outgoing)
            if key in seen:
                return
            seen.add(key)
            other = mint(entry, target_type, occurred)
            if other is None or other == subject:
                return
            src, dst = (subject, other) if outgoing else (other, subject)
            _upsert_edge(session, src, dst, edge_type, raw_id, occurred.date())
            setattr(stats, edge_type, getattr(stats, edge_type) + 1)

        if payload.get("entity_type") == "person":
            for entry in claims.get("P108") or []:
                edge_type = "formerly_at" if entry.get("end") else "employed_by"
                link(entry, edge_type, "org", outgoing=True)
            for entry in claims.get("P69") or []:
                link(entry, "educated_at", "org", outgoing=True)
            for entry in claims.get("P184") or []:  # subject's doctoral advisor
                link(entry, "advised_by", "person", outgoing=True)
            for entry in claims.get("P185") or []:  # subject's doctoral student → inverted
                link(entry, "advised_by", "person", outgoing=False)
            for entry in claims.get("P800") or []:  # what they are famous for building
                link(entry, "notable_work", "work", outgoing=True)
        elif payload.get("entity_type") == "org":
            for prop, edge_type in org_props:
                for entry in claims.get(prop) or []:
                    link(entry, edge_type, "person", outgoing=False)
            # Ownership / backing. Owners and investors default to org — the QID-direct
            # enrichment pass corrects the type from P31 when it later fetches them.
            for entry in claims.get("P749") or []:  # subject's parent organization
                link(entry, "subsidiary_of", "org", outgoing=True)
            for entry in claims.get("P355") or []:  # subject's subsidiary → inverted
                link(entry, "subsidiary_of", "org", outgoing=False)
            for entry in claims.get("P127") or []:
                link(entry, "owned_by", "org", outgoing=True)
            for entry in claims.get("P1951") or []:  # investors point INTO the org
                link(entry, "invested_in", "org", outgoing=False)
            # An org resolved from an HF handle owns every tracked model under that handle —
            # the edge that connects the team subgraph to the artifacts people actually browse.
            # The handle comes from the event when the handle path fetched it, else from the
            # entity (resolve persists it there), so a QID-path re-fetch doesn't lose the link.
            handle = payload.get("org_handle") or session.execute(
                text("SELECT attrs->>'hf_org_handle' FROM entities WHERE id = :id"),
                {"id": subject},
            ).scalar()
            if handle:
                model_rows = session.execute(
                    text(
                        "SELECT id FROM entities WHERE attrs->'anchors'->>'hf' LIKE :pre"
                        " AND created_at <= :as_of"
                    ),
                    {"pre": f"{handle}/%", "as_of": as_of},
                ).all()
                for (model_id,) in model_rows:
                    model = canonical(int(model_id))
                    if model == subject:
                        continue
                    _upsert_edge(
                        session, model, subject, "developed_by", row["raw_id"], occurred.date()
                    )
                    stats.developed_by += 1


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
