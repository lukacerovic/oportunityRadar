"""Graph AI explanations (``graph/explain.py`` + the ``/graph/explain`` API) — subgraph pack,
hash-gated regeneration, and serving. Runs on ``clean_db`` with the ``mock`` provider ($0)."""

from __future__ import annotations

import itertools
import json
from datetime import UTC, datetime

from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session

from seismo.graph.explain import build_subgraph, evidence_pack, explain_entity, run_explain

_UID = itertools.count(1)
NOW = datetime(2026, 7, 28, 12, 0, tzinfo=UTC)


def _entity(session: Session, name: str, etype: str, info: dict | None = None) -> int:
    attrs: dict = {"anchors": {}}
    if info:
        attrs["wikidata"] = info
    return int(
        session.execute(
            text(
                "INSERT INTO entities (entity_type, canonical_name, created_at, attrs) "
                "VALUES (:t, :n, :c, CAST(:a AS JSONB)) RETURNING id"
            ),
            {"t": etype, "n": name, "c": NOW, "a": json.dumps(attrs)},
        ).scalar_one()
    )


def _edge(session: Session, src: int, dst: int, edge_type: str) -> None:
    session.execute(
        text(
            "INSERT INTO entity_graph_edges (src_entity_id, dst_entity_id, edge_type, weight) "
            "VALUES (:s, :d, :t, 1.0)"
        ),
        {"s": src, "d": dst, "t": edge_type},
    )


def _mira_cluster(session: Session) -> tuple[int, int, int]:
    model = _entity(session, "thinkingmachines/inkling", "model")
    org = _entity(
        session, "Thinking Machines Lab", "org",
        {"description": "American AI company", "inception": "2025"},
    )
    mira = _entity(
        session, "Mira Murati", "person",
        {"description": "business executive", "positions": ["CTO — OpenAI (2022–2024)"]},
    )
    _edge(session, model, org, "developed_by")
    _edge(session, mira, org, "founded")
    session.flush()
    return model, org, mira


def test_pack_and_hash_track_subgraph_content(clean_db: Session) -> None:
    session = clean_db
    model, org, mira = _mira_cluster(session)

    sub = build_subgraph(session, model)
    assert sub is not None and len(sub.edges) == 2  # both edges live inside the 2-hop hood
    pack = evidence_pack(sub)
    assert "Mira Murati --founded--> Thinking Machines Lab" in pack
    assert "positions: CTO — OpenAI (2022–2024)" in pack
    h1 = sub.hash

    _edge(session, mira, _entity(session, "OpenAI", "org"), "formerly_at")
    session.flush()
    sub2 = build_subgraph(session, model)
    assert sub2 is not None and sub2.hash != h1, "new edge must change the fingerprint"


def test_explain_generates_then_skips_unchanged(clean_db: Session) -> None:
    session = clean_db
    model, _org, _mira = _mira_cluster(session)

    outcome, cost = explain_entity(session, model)
    assert outcome == "generated" and cost == 0  # mock provider
    row = session.execute(
        text("SELECT content, model FROM graph_explanations WHERE entity_id = :i"), {"i": model}
    ).one()
    assert row[1] == "mock"
    assert "thinkingmachines/inkling" in row[0]["overview"]

    assert explain_entity(session, model)[0] == "unchanged", "same hash → no regeneration"

    lonely = _entity(session, "no-edges-yet", "project")
    session.flush()
    assert explain_entity(session, lonely)[0] == "empty"


def test_api_serves_stored_and_flags_stale(clean_db: Session) -> None:
    from seismo.api.app import app, get_session

    session = clean_db
    model, _org, mira = _mira_cluster(session)
    explain_entity(session, model)
    session.flush()

    app.dependency_overrides[get_session] = lambda: session
    client = TestClient(app)
    try:
        body = client.get("/graph/explain", params={"entity_id": model}).json()
        assert body["entity_name"] == "thinkingmachines/inkling"
        assert body["model"] == "mock" and body["stale"] is False

        # New enrichment lands -> stored text is stale until the next explain run.
        _edge(session, mira, _entity(session, "OpenAI", "org"), "formerly_at")
        session.flush()
        assert client.get("/graph/explain", params={"entity_id": model}).json()["stale"] is True

        assert client.get("/graph/explain", params={"entity_id": 999999}).status_code == 404
    finally:
        app.dependency_overrides.clear()


def test_run_explain_batches_trending_only(clean_db: Session) -> None:
    session = clean_db
    model, _org, _mira = _mira_cluster(session)
    # Make the model trending (breakout) so the batch selector picks it.
    session.execute(
        text(
            "INSERT INTO momentum_states (entity_id, day, state, score) "
            "VALUES (:i, :d, 'breakout', 0.9)"
        ),
        {"i": model, "d": NOW.date()},
    )
    session.flush()

    stats = run_explain(session, limit=10)
    assert stats.candidates == 1 and stats.generated == 1 and stats.failed == 0
    stats2 = run_explain(session, limit=10)
    assert stats2.unchanged == 1 and stats2.generated == 0
