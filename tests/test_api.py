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


def test_gate_week_audit(clean_db: Session) -> None:
    session = clean_db
    t0 = datetime(2024, 1, 1, tzinfo=UTC)
    winner = _entity(session, "rocket", created=t0, category="model-efficiency")
    gap = _entity(session, "hypey", created=t0, category="prompt-tooling")
    week = "2026-07-06"  # a Monday → ISO 2026-W28

    def _decision(eid: int, decision: str, score: float, comps: dict) -> None:
        session.execute(
            text(
                "INSERT INTO gate_decisions (entity_id, week, decision, score, components)"
                " VALUES (:e, :w, :d, :s, CAST(:c AS JSONB))"
            ),
            {"e": eid, "w": week, "d": decision, "s": score, "c": _json(comps)},
        )

    _decision(
        winner,
        "pass",
        0.42,
        {
            "M": 0.7,
            "R": 1.0,
            "N": 0.6,
            "score": 0.42,
            "peak_state": "breakout",
            "category": "model-efficiency",
            "reach_lines": 3,
            "reach_core": True,
        },
    )
    _decision(
        gap,
        "suppressed",
        0.0,
        {
            "M": 0.7,
            "R": 0.0,
            "N": 0.3,
            "score": 0.0,
            "peak_state": "breakout",
            "category": "prompt-tooling",
            "reach_lines": 0,
            "reason": "unmapped_reach",
        },
    )
    session.flush()

    d = _client(session).get("/gate/2026-W28").json()
    assert d["briefs_budget"] == 5
    assert [p["name"] for p in d["passed"]] == ["rocket"]
    assert d["passed"][0]["components"]["R"] == 1.0
    assert [s["name"] for s in d["suppressed"]] == ["hypey"]
    assert d["suppressed"][0]["components"]["reason"] == "unmapped_reach"
    assert d["map_gaps"] == {"prompt-tooling": 1}
    assert "2026-W28" in d["available_weeks"]

    # 'current'/'latest' resolves to the most recent week that has decisions.
    assert _client(session).get("/gate/latest").json()["week"] == week


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


def test_briefs_inbox_detail_and_review(clean_db: Session) -> None:
    session = clean_db
    t0 = datetime(2024, 1, 1, tzinfo=UTC)
    eid = _entity(session, "vllm", created=t0, category="inference-runtime")
    body = {
        "entity_ref": "vllm",
        "mechanisms": ["substitution"],
        "transmission_path": [{"from_node": "vllm", "to_node": "cost", "effect": "falls"}],
        "exposures": [
            {"kind": "ticker", "ref": "NVDA", "revenue_line": "datacenter",
             "direction": "negative", "magnitude_class": "material"}
        ],
        "counter_mechanism": "Jevons.",
        "observables": [
            {"statement": "tokens/customer", "source": "system", "system_metric": "x",
             "horizon": "quarters", "direction_if_thesis_holds": "down"}
        ],
        "confidence": "med",
        "horizon": "1-2y",
        "summary": "a thesis",
        "evidence_refs": [1],
    }
    brief_id = int(
        session.execute(
            text(
                "INSERT INTO impact_briefs (entity_id, version, as_of, brief, status, model)"
                " VALUES (:e, 1, :as_of, CAST(:b AS JSONB), 'draft', 'mock') RETURNING id"
            ),
            {"e": eid, "as_of": t0, "b": _json(body)},
        ).scalar_one()
    )
    session.flush()
    client = _client(session)

    # inbox shows the draft
    inbox = client.get("/briefs").json()
    assert any(row["id"] == brief_id and row["status"] == "draft" for row in inbox)

    # detail renders the schema
    d = client.get(f"/briefs/{eid}").json()
    assert d["mechanisms"] == ["substitution"]
    assert d["exposures"][0]["ref"] == "NVDA"
    assert d["counter_mechanism"] == "Jevons."
    assert d["versions"] == [1]

    # reject requires a reason
    assert client.post(f"/briefs/{brief_id}/decision", params={"decision": "reject"}).status_code == 400

    # publish flips status; a second decision on a non-draft 409s (immutable)
    res = client.post(f"/briefs/{brief_id}/decision", params={"decision": "publish"}).json()
    assert res["status"] == "published"
    assert (
        client.post(f"/briefs/{brief_id}/decision", params={"decision": "publish"}).status_code
        == 409
    )
    status = session.execute(
        text("SELECT status FROM impact_briefs WHERE id = :id"), {"id": brief_id}
    ).scalar_one()
    assert status == "published"
