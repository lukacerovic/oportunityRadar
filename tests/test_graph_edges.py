"""Feature 1 — typed entity-graph edges (``built_by`` / ``cited`` / ``depends_on``).

Exercises the pure ``derive_edges`` derivation directly (no CLI): edges are minted from
already-attached ``repo_contributors`` / ``repo_readme`` / ``pypi_metadata`` events, person/paper
entities are created with the resolver's anchor keys, an R1 self-loop is skipped, ``depends_on``
only links already-tracked packages, and re-running is idempotent.

Runs on ``clean_db`` (the entity/edge/event tables are emptied) so exact counts are assertable;
every write lives inside the rolled-back transaction.
"""

from __future__ import annotations

import itertools
import json
from datetime import UTC, datetime

from sqlalchemy import text
from sqlalchemy.orm import Session

from seismo.graph.edges import derive_edges

_UID = itertools.count(1)
AS_OF = datetime(2026, 7, 1, 12, 0, tzinfo=UTC)
OCCURRED = datetime(2026, 6, 15, 12, 0, tzinfo=UTC)


# --- helpers ----------------------------------------------------------------


def _entity(
    session: Session,
    name: str,
    *,
    etype: str = "project",
    anchors: dict[str, str] | None = None,
    created: datetime = OCCURRED,
) -> int:
    attrs = {"anchors": anchors or {}}
    return int(
        session.execute(
            text(
                "INSERT INTO entities (entity_type, canonical_name, created_at, attrs) "
                "VALUES (:t, :n, :c, CAST(:a AS JSONB)) RETURNING id"
            ),
            {"t": etype, "n": name, "c": created, "a": json.dumps(attrs)},
        ).scalar_one()
    )


def _event(
    session: Session,
    entity_id: int,
    *,
    event_type: str,
    payload: dict,
    source: str = "github",
    occurred: datetime = OCCURRED,
) -> int:
    ev = int(
        session.execute(
            text(
                "INSERT INTO raw_events "
                "(source, source_event_uid, event_type, occurred_at, payload)"
                " VALUES (:s, :u, :et, :o, CAST(:p AS JSONB)) RETURNING id"
            ),
            {
                "s": source,
                "u": f"test:{next(_UID)}",
                "et": event_type,
                "o": occurred,
                "p": json.dumps(payload),
            },
        ).scalar_one()
    )
    session.execute(
        text(
            "INSERT INTO entity_links (entity_id, raw_event_id, rule, confidence, "
            "evidence_occurred_at) VALUES (:e, :ev, 'attach', 1.0, :o)"
        ),
        {"e": entity_id, "ev": ev, "o": occurred},
    )
    return ev


def _merge(session: Session, loser: int, survivor: int, *, justified: datetime = OCCURRED) -> None:
    session.execute(
        text(
            "INSERT INTO entity_merges (loser_id, survivor_id, justified_at, rule, confidence, "
            "decided_by, active) VALUES (:l, :s, :j, 'R1', 0.99, 'auto', true)"
        ),
        {"l": loser, "s": survivor, "j": justified},
    )


def _edges(session: Session, edge_type: str | None = None) -> list[dict]:
    sql = (
        "SELECT src_entity_id, dst_entity_id, edge_type, evidence_refs, weight "
        "FROM entity_graph_edges"
    )
    params: dict = {}
    if edge_type is not None:
        sql += " WHERE edge_type = :et"
        params["et"] = edge_type
    return [dict(r) for r in session.execute(text(sql), params).mappings()]


def _entity_by_anchor(session: Session, registry: str, native_id: str) -> int | None:
    row = session.execute(
        text("SELECT id FROM entities WHERE attrs->'anchors'->>:reg = :nid"),
        {"reg": registry, "nid": native_id},
    ).first()
    return None if row is None else int(row[0])


# --- built_by ---------------------------------------------------------------


def test_built_by_edge_and_person_created(clean_db: Session) -> None:
    session = clean_db
    repo = _entity(session, "own/repo", anchors={"github": "own/repo"})
    raw = _event(
        session,
        repo,
        event_type="repo_contributors",
        payload={"full_name": "own/repo", "contributors": [{"login": "alice", "contributions": 9}]},
    )
    session.flush()

    stats = derive_edges(session, AS_OF)

    assert stats.built_by == 1
    assert stats.persons_created == 1
    person = _entity_by_anchor(session, "github", "user:alice")
    assert person is not None
    edges = _edges(session, "built_by")
    assert len(edges) == 1
    assert edges[0]["src_entity_id"] == person and edges[0]["dst_entity_id"] == repo
    assert edges[0]["evidence_refs"] == [raw]


# --- cited ------------------------------------------------------------------


def test_cited_edge_from_readme_arxiv(clean_db: Session) -> None:
    session = clean_db
    repo = _entity(session, "own/repo", anchors={"github": "own/repo"})
    raw = _event(
        session,
        repo,
        event_type="repo_readme",
        payload={"full_name": "own/repo", "text": "Built on DeepSeek-V2 (see arXiv:2405.04434)."},
    )
    session.flush()

    stats = derive_edges(session, AS_OF)

    assert stats.cited == 1
    assert stats.papers_created == 1
    paper = _entity_by_anchor(session, "arxiv", "2405.04434")
    assert paper is not None
    edges = _edges(session, "cited")
    assert len(edges) == 1
    assert edges[0]["src_entity_id"] == repo and edges[0]["dst_entity_id"] == paper
    assert edges[0]["evidence_refs"] == [raw]


def test_cited_self_loop_from_r1_merge_is_skipped(clean_db: Session) -> None:
    """A paper already R1-merged into its own repo must not produce a repo→repo self-loop edge."""
    session = clean_db
    repo = _entity(session, "own/repo", anchors={"github": "own/repo"})
    paper = _entity(session, "2401.12345", etype="paper", anchors={"arxiv": "2401.12345"})
    _merge(session, loser=paper, survivor=repo)  # R1 folded the paper into the repo
    _event(
        session,
        repo,
        event_type="repo_readme",
        payload={"full_name": "own/repo", "text": "Our paper: arXiv:2401.12345."},
    )
    session.flush()

    stats = derive_edges(session, AS_OF)

    assert stats.cited == 0, "canonical src == canonical dst — self-loop must be skipped"
    assert stats.papers_created == 0, "the paper already exists (it was merged, not recreated)"
    assert _edges(session, "cited") == []


# --- depends_on -------------------------------------------------------------


def test_depends_on_links_tracked_only(clean_db: Session) -> None:
    session = clean_db
    dependent = _entity(session, "langchain", anchors={"pypi": "langchain"})
    dependency = _entity(session, "pydantic", anchors={"pypi": "pydantic"})
    raw = _event(
        session,
        dependent,
        event_type="pypi_metadata",
        source="pypi",
        payload={
            "name": "langchain",
            "requires_dist": ["Pydantic (>=2.0)", "some-untracked-pkg (>=1.0)"],
        },
    )
    session.flush()

    stats = derive_edges(session, AS_OF)

    assert stats.depends_on == 1, "only the tracked dependency is linked, never the untracked one"
    edges = _edges(session, "depends_on")
    assert len(edges) == 1
    assert edges[0]["src_entity_id"] == dependent and edges[0]["dst_entity_id"] == dependency
    assert edges[0]["evidence_refs"] == [raw]
    # The untracked package was never minted as an entity.
    assert _entity_by_anchor(session, "pypi", "some-untracked-pkg") is None


# --- idempotency ------------------------------------------------------------


def test_rerun_is_idempotent(clean_db: Session) -> None:
    session = clean_db
    repo = _entity(session, "own/repo", anchors={"github": "own/repo"})
    _event(
        session,
        repo,
        event_type="repo_contributors",
        payload={"full_name": "own/repo", "contributors": [{"login": "alice", "contributions": 9}]},
    )
    _event(
        session,
        repo,
        event_type="repo_readme",
        payload={"full_name": "own/repo", "text": "See arXiv:2405.04434 for details."},
    )
    session.flush()

    first = derive_edges(session, AS_OF)
    session.flush()
    n_after_first = len(_edges(session))
    n_persons_first = int(
        session.execute(
            text("SELECT count(*) FROM entities WHERE entity_type = 'person'")
        ).scalar_one()
    )

    second = derive_edges(session, AS_OF)
    session.flush()

    assert n_after_first == len(_edges(session)), "no duplicate edges on re-run (unique constraint)"
    assert first.edges_upserted == second.edges_upserted
    # Second run creates no new person/paper entities — the anchors already exist.
    assert second.persons_created == 0 and second.papers_created == 0
    assert n_persons_first == int(
        session.execute(
            text("SELECT count(*) FROM entities WHERE entity_type = 'person'")
        ).scalar_one()
    )
    # Weight is refreshed (not accumulated) and evidence_refs is a single ref, not appended twice.
    for edge in _edges(session):
        assert edge["weight"] == 1.0
        assert len(edge["evidence_refs"]) == 1
