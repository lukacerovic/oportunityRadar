"""Stage 5 — read + curation API (doc 10). Exercises the real routes against a rolled-back
transaction by overriding the session dependency, so the endpoints run their actual SQL."""

from __future__ import annotations

import itertools
from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
from sqlalchemy import text
from sqlalchemy.orm import Session

from seismo.api.app import app, get_session

_UID = itertools.count(1)


def _client(session: Session) -> TestClient:
    app.dependency_overrides[get_session] = lambda: session
    return TestClient(app)


def _json(v: dict) -> str:
    import json

    return json.dumps(v)


def _entity(
    session: Session,
    name: str,
    *,
    created: datetime,
    category: str | None = None,
    attrs: dict | None = None,
) -> int:
    eid = int(
        session.execute(
            text(
                "INSERT INTO entities (entity_type, canonical_name, category, created_at, attrs)"
                " VALUES ('project', :n, :cat, :c, CAST(:a AS JSONB)) RETURNING id"
            ),
            {"n": name, "cat": category, "c": created, "a": _json(attrs or {})},
        ).scalar_one()
    )
    if category is not None:
        session.execute(
            text(
                "INSERT INTO entity_category_history (entity_id, category, effective_at)"
                " VALUES (:e, :cat, :eff)"
            ),
            {"e": eid, "cat": category, "eff": created},
        )
    return eid


def _momentum(session: Session, eid: int, day: datetime, state: str, p: float) -> None:
    session.execute(
        text(
            "INSERT INTO momentum_states (entity_id, day, state, score, inputs)"
            " VALUES (:e, :d, :s, :sc, CAST(:i AS JSONB))"
        ),
        {
            "e": eid,
            "d": day.date(),
            "s": state,
            "sc": p,
            "i": _json({"P": p, "provisional": False}),
        },
    )


def test_health_ok(clean_db: Session) -> None:
    assert _client(clean_db).get("/health").json()["ok"] is True


def test_radar_ranks_breakout_first_with_one_liner(clean_db: Session) -> None:
    session = clean_db
    t0 = datetime(2024, 1, 1, tzinfo=UTC)
    hot = _entity(session, "rocket", created=t0, category="inference-runtime")
    cold = _entity(session, "sleeper", created=t0)
    _momentum(session, hot, t0, "breakout", 0.99)
    _momentum(session, cold, t0, "dormant", 0.0)
    session.execute(
        text(
            "INSERT INTO comprehension_cards (entity_id, version, as_of, card, model, status)"
            " VALUES (:e, 1, :d, CAST(:c AS JSONB), 'mock', 'ok')"
        ),
        {
            "e": hot,
            "d": t0,
            "c": _json({"what_it_is": "A fast engine.", "maturity_stage": "distribution"}),
        },
    )
    session.flush()

    r = (
        _client(session)
        .get("/radar", params={"as_of": (t0 + timedelta(days=1)).isoformat()})
        .json()
    )
    names = [e["name"] for e in r["entities"]]
    assert names.index("rocket") < names.index("sleeper"), "breakout ranks above dormant"
    rocket = next(e for e in r["entities"] if e["name"] == "rocket")
    assert rocket["state"] == "breakout" and rocket["one_liner"] == "A fast engine."
    assert rocket["velocity_pctl"] == 0.99

    filtered = _client(session).get("/radar", params={"state": "breakout"}).json()
    assert {e["name"] for e in filtered["entities"]} == {"rocket"}


def test_dossier_returns_card_and_history(clean_db: Session) -> None:
    session = clean_db
    t0 = datetime(2024, 1, 1, tzinfo=UTC)
    eid = _entity(
        session,
        "proj",
        created=t0,
        category="inference-runtime",
        attrs={"anchors": {"github": "acme/proj"}, "owner": "acme"},
    )
    session.execute(
        text(
            "INSERT INTO raw_events (source, source_event_uid, event_type, occurred_at, payload)"
            " VALUES ('github','g1','repo_snapshot',:o,'{}') RETURNING id"
        ),
        {"o": t0},
    )
    ev = session.execute(text("SELECT id FROM raw_events WHERE source_event_uid='g1'")).scalar_one()
    session.execute(
        text(
            "INSERT INTO entity_links"
            " (entity_id, raw_event_id, rule, confidence, evidence_occurred_at)"
            " VALUES (:e, :ev, 'attach', 1.0, :o)"
        ),
        {"e": eid, "ev": ev, "o": t0},
    )
    _momentum(session, eid, t0, "simmering", 0.7)
    session.execute(
        text(
            "INSERT INTO entity_metrics_daily (entity_id, metric, day, value)"
            " VALUES (:e, 'gh_stars', :d, 120)"
        ),
        {"e": eid, "d": t0.date()},
    )
    session.execute(
        text(
            "INSERT INTO comprehension_cards (entity_id, version, as_of, card, model, status)"
            " VALUES (:e, 1, :d, CAST(:c AS JSONB), 'mock', 'ok')"
        ),
        {
            "e": eid,
            "d": t0,
            "c": _json(
                {"what_it_is": "x", "category": "inference-runtime", "category_disputed": False}
            ),
        },
    )
    session.flush()

    d = (
        _client(session)
        .get(f"/entities/{eid}", params={"as_of": (t0 + timedelta(days=1)).isoformat()})
        .json()
    )
    assert d["name"] == "proj" and d["anchors"] == {"github": "acme/proj"}
    assert d["state"] == "simmering" and d["card"]["what_it_is"] == "x"
    assert d["card_versions"] == [1]
    assert any(mseries["metric"] == "gh_stars" for mseries in d["metrics"])


def test_search_finds_by_trigram(clean_db: Session) -> None:
    session = clean_db
    t0 = datetime(2024, 1, 1, tzinfo=UTC)
    _entity(session, "vllm-project", created=t0)
    session.flush()
    hits = _client(session).get("/search", params={"q": "vllm"}).json()
    assert any(h["name"] == "vllm-project" for h in hits)


def test_queue_and_merge_decision(clean_db: Session) -> None:
    session = clean_db
    t0 = datetime(2024, 1, 1, tzinfo=UTC)
    a = _entity(session, "dupe-a", created=t0)
    b = _entity(session, "dupe-b", created=t0 + timedelta(days=1))
    qid = int(
        session.execute(
            text(
                "INSERT INTO entity_merge_queue (entity_a, entity_b, confidence, evidence, status)"
                " VALUES (:a, :b, 0.85, '{}', 'pending') RETURNING id"
            ),
            {"a": a, "b": b},
        ).scalar_one()
    )
    session.flush()
    client = _client(session)

    q = client.get("/queue").json()
    assert any(item["id"] == qid for item in q)

    res = client.post(f"/merge-queue/{qid}/decision", params={"decision": "merge"}).json()
    assert res["merged"] is True and res["status"] == "merged"
    # survivor is the earlier-created entity; loser now points at it.
    merged_into = session.execute(
        text("SELECT merged_into FROM entities WHERE id = :b"), {"b": b}
    ).scalar_one()
    assert merged_into == a
    # queue item is resolved -> no longer pending.
    assert not client.get("/queue").json()
