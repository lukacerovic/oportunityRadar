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


def _attach_source(session: Session, eid: int, source: str, occurred: datetime) -> None:
    """Attach a raw event from ``source`` to an entity, the way /radar reads collection source."""
    rid = int(
        session.execute(
            text(
                "INSERT INTO raw_events"
                " (source, source_event_uid, event_type, occurred_at, payload)"
                " VALUES (:s, :uid, 'test', :o, CAST('{}' AS JSONB)) RETURNING id"
            ),
            {"s": source, "uid": f"{source}-{next(_UID)}", "o": occurred},
        ).scalar_one()
    )
    session.execute(
        text(
            "INSERT INTO entity_links"
            " (entity_id, raw_event_id, rule, confidence, evidence_occurred_at)"
            " VALUES (:e, :r, 'attach', 1.0, :o)"
        ),
        {"e": eid, "r": rid, "o": occurred},
    )


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


def test_radar_source_filter_and_counts_are_by_origin(clean_db: Session) -> None:
    session = clean_db
    t0 = datetime(2024, 1, 1, tzinfo=UTC)
    # A GitHub repo that also trended on HN: its origin is still GitHub, not Hacker News.
    repo = _entity(session, "acme/tool", created=t0, attrs={"anchors": {"github": "acme/tool"}})
    _entity(session, "A Paper", created=t0, attrs={"anchors": {"arxiv": "2405.00001"}})
    _entity(session, "Kimi K3", created=t0, attrs={"anchors": {"web": "kimi-k3"}})
    _attach_source(session, repo, "github", t0)
    _attach_source(session, repo, "hn", t0)  # HN attention on a GitHub entity
    session.flush()

    as_of = (t0 + timedelta(days=1)).isoformat()
    r = _client(session).get("/radar", params={"as_of": as_of}).json()
    by_name = {e["name"]: e for e in r["entities"]}
    # The `sources` array still records every collector that touched an entity (raw provenance).
    assert set(by_name["acme/tool"]["sources"]) == {"github", "hn"}
    # ...but the pill COUNTS are by origin: the repo counts as GitHub, never Hacker News.
    assert r["source_counts"] == {"github": 1, "arxiv": 1, "hf": 0, "hn": 1}

    # Selecting Hacker News returns ONLY the HN-native launch — no GitHub repo bleeds in.
    hn = _client(session).get("/radar", params={"as_of": as_of, "source": "hn"}).json()
    assert {e["name"] for e in hn["entities"]} == {"Kimi K3"}
    # Selecting GitHub returns the repo (which trended on HN) but not the launch.
    gh = _client(session).get("/radar", params={"as_of": as_of, "source": "github"}).json()
    assert {e["name"] for e in gh["entities"]} == {"acme/tool"}


def test_dossier_exposes_readable_sources(clean_db: Session) -> None:
    session = clean_db
    t0 = datetime(2024, 1, 1, tzinfo=UTC)
    eid = _entity(
        session,
        "Kimi K3",
        created=t0,
        attrs={"anchors": {"web": "kimi-k3"}, "text": "Kimi K3 is a model."},
    )

    def _raw_event(source: str, etype: str, payload: dict) -> int:
        rid = int(
            session.execute(
                text(
                    "INSERT INTO raw_events"
                    " (source, source_event_uid, event_type, occurred_at, payload)"
                    " VALUES (:s, :uid, :et, :o, CAST(:p AS JSONB)) RETURNING id"
                ),
                {
                    "s": source,
                    "uid": f"{source}-{next(_UID)}",
                    "et": etype,
                    "o": t0,
                    "p": _json(payload),
                },
            ).scalar_one()
        )
        session.execute(
            text(
                "INSERT INTO entity_links (entity_id, raw_event_id, rule, confidence)"
                " VALUES (:e, :r, 'attach', 1.0)"
            ),
            {"e": eid, "r": rid},
        )
        return rid

    _raw_event(
        "hn", "story", {"title": "Kimi K3 is now live", "url": "https://kimi.com", "points": 641}
    )
    _raw_event(
        "web",
        "launch_page",
        {"slug": "kimi-k3", "url": "https://kimi.com", "text": "Kimi K3 is a 1T MoE model."},
    )
    # snapshots excluded
    _raw_event("hf", "model_snapshot", {"id": "moonshotai/kimi-k3", "downloads": 5})
    session.flush()

    d = _client(session).get(f"/entities/{eid}").json()
    assert d["description"] == "Kimi K3 is a model."
    kinds = {e["kind"] for e in d["evidence"]}
    assert kinds == {"Hacker News", "Launch page"}  # the model_snapshot is filtered out
    hn = next(e for e in d["evidence"] if e["kind"] == "Hacker News")
    assert hn["score"] == 641 and hn["url"] == "https://kimi.com"
    launch = next(e for e in d["evidence"] if e["kind"] == "Launch page")
    assert launch["text"] == "Kimi K3 is a 1T MoE model."


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
            {
                "kind": "ticker",
                "ref": "NVDA",
                "revenue_line": "datacenter",
                "direction": "negative",
                "magnitude_class": "material",
            }
        ],
        "counter_mechanism": "Jevons paradox: cheaper inference grows total volume.",
        "observables": [
            {
                "statement": "tokens/customer",
                "source": "system",
                "system_metric": "x",
                "horizon": "quarters",
                "direction_if_thesis_holds": "down",
            }
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
    assert d["counter_mechanism"] == "Jevons paradox: cheaper inference grows total volume."
    assert d["versions"] == [1]

    # reject requires a reason
    assert (
        client.post(f"/briefs/{brief_id}/decision", params={"decision": "reject"}).status_code
        == 400
    )

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


def test_changes_and_calibration_and_scoring(clean_db: Session) -> None:
    session = clean_db
    t0 = datetime(2026, 6, 1, tzinfo=UTC)
    e = _entity(session, "riser", created=t0)
    # a change row
    session.execute(
        text(
            "INSERT INTO changes_daily (day, kind, entity_id, text, payload) "
            "VALUES (:d, 'state_up', :e, '↑ riser: simmering → breakout', '{}')"
        ),
        {"d": t0.date(), "e": e},
    )
    # a calibration snapshot
    session.execute(
        text(
            "INSERT INTO calibration_snapshots (day, metric, value, sample_n, detail) "
            "VALUES (:d, 'breakout_survival', 0.6, 5, '{}')"
        ),
        {"d": t0.date()},
    )
    # a published brief with a system observable to auto-evaluate
    body = {
        "entity_ref": "riser",
        "mechanisms": ["substitution"],
        "transmission_path": [{"from_node": "a", "to_node": "b", "effect": "x"}],
        "exposures": [
            {
                "kind": "ticker",
                "ref": "NVDA",
                "revenue_line": "datacenter",
                "direction": "negative",
                "magnitude_class": "material",
            }
        ],
        "counter_mechanism": "Jevons paradox: cheaper inference grows total volume.",
        "observables": [
            {
                "statement": "downloads fall",
                "source": "system",
                "system_metric": "hf_downloads_30d",
                "horizon": "quarters",
                "direction_if_thesis_holds": "down",
            }
        ],
        "confidence": "med",
        "horizon": "quarters",
        "summary": "s",
        "evidence_refs": [],
    }
    bid = int(
        session.execute(
            text(
                "INSERT INTO impact_briefs (entity_id, version, as_of, brief, status, model,"
                " reviewed_at, created_at) VALUES (:e, 1, :t, CAST(:b AS JSONB), 'published',"
                " 'mock', :t, :t) RETURNING id"
            ),
            {"e": e, "t": t0, "b": _json(body)},
        ).scalar_one()
    )
    # both points must fall within [published, now]; the score-packet endpoint uses the real clock,
    # so keep d1 shortly after publication (not months out, which would land in the future).
    session.execute(
        text(
            "INSERT INTO entity_metrics_daily (entity_id, metric, day, value) VALUES "
            "(:e, 'hf_downloads_30d', :d0, 1000), (:e, 'hf_downloads_30d', :d1, 400)"
        ),
        {"e": e, "d0": t0.date(), "d1": (t0 + timedelta(days=14)).date()},
    )
    session.flush()
    client = _client(session)

    ch = client.get(f"/changes/{t0.date().isoformat()}").json()
    assert ch["total"] == 1 and "state_up" in ch["groups"]

    cal = client.get("/calibration").json()
    assert cal["latest"]["breakout_survival"]["value"] == 0.6

    packet = client.get(f"/briefs/{e}/score-packet").json()
    assert packet["observable_evals"][0]["status"] == "on_track"  # downloads fell, thesis said down

    res = client.post(
        f"/briefs/{bid}/score", params={"materialized": "yes", "counter_was_better": "true"}
    ).json()
    assert res["materialized"] == "yes"
    stored = session.execute(
        text("SELECT materialized FROM brief_scores WHERE brief_id = :b"), {"b": bid}
    ).scalar_one()
    assert stored == "yes"
