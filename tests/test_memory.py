"""Stage 8 — Memory & synthesis (doc 09). The deterministic Changes diffs, the automated momentum
calibration ratios, and the brief forward-scoring assembler with its A-7 auto-evaluation of
``source='system'`` observables. All on ``clean_db`` ($0, no LLM — Stage 8 is deterministic)."""

from __future__ import annotations

import itertools
import json
from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from seismo.memory.calibration import run_momentum_review
from seismo.memory.changes import compute_changes
from seismo.memory.scoring import assemble_score_packet, record_score

_UID = itertools.count(1)


# --- helpers ----------------------------------------------------------------


def _entity(session: Session, name: str, *, created: datetime) -> int:
    eid = int(
        session.execute(
            text(
                "INSERT INTO entities (entity_type, canonical_name, created_at, attrs) "
                "VALUES ('project', :n, :c, '{}') RETURNING id"
            ),
            {"n": name, "c": created},
        ).scalar_one()
    )
    return eid


def _attach(session: Session, eid: int, occurred: datetime) -> None:
    ev = int(
        session.execute(
            text(
                "INSERT INTO raw_events (source, source_event_uid, event_type, occurred_at,"
                " payload) VALUES ('github', :u, 'repo_discovered', :o, '{}') RETURNING id"
            ),
            {"u": f"m:{next(_UID)}", "o": occurred},
        ).scalar_one()
    )
    session.execute(
        text(
            "INSERT INTO entity_links (entity_id, raw_event_id, rule, confidence,"
            " evidence_occurred_at) VALUES (:e, :ev, 'attach', 1.0, :o)"
        ),
        {"e": eid, "ev": ev, "o": occurred},
    )


def _state(session: Session, eid: int, day: date, state: str) -> None:
    session.execute(
        text(
            "INSERT INTO momentum_states (entity_id, day, state, score, inputs) "
            "VALUES (:e, :d, :s, 0.5, '{}') "
            "ON CONFLICT (entity_id, day) DO UPDATE SET state = EXCLUDED.state"
        ),
        {"e": eid, "d": day, "s": state},
    )


def _metric(session: Session, eid: int, metric: str, day: date, value: float) -> None:
    session.execute(
        text(
            "INSERT INTO entity_metrics_daily (entity_id, metric, day, value) "
            "VALUES (:e, :m, :d, :v) ON CONFLICT (entity_id, metric, day) DO UPDATE "
            "SET value = EXCLUDED.value"
        ),
        {"e": eid, "m": metric, "d": day, "v": value},
    )


def _brief(
    session: Session,
    eid: int,
    *,
    observables: list[dict],
    created: datetime,
    status: str = "published",
) -> int:
    body = {
        "entity_ref": "e",
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
        "counter_mechanism": "jevons",
        "observables": observables,
        "confidence": "med",
        "horizon": "quarters",
        "summary": "s",
        "evidence_refs": [],
    }
    bid = int(
        session.execute(
            text(
                "INSERT INTO impact_briefs (entity_id, version, as_of, brief, status, model,"
                " reviewed_at, created_at) VALUES (:e, 1, :as_of, CAST(:b AS JSONB), :st, 'mock',"
                " :rev, :created) RETURNING id"
            ),
            {
                "e": eid,
                "as_of": created,
                "b": json.dumps(body),
                "st": status,
                "rev": created if status == "published" else None,
                "created": created,
            },
        ).scalar_one()
    )
    return bid


# --- Changes view (doc 09 §1) -----------------------------------------------


def test_changes_state_transitions_and_promotions(clean_db: Session) -> None:
    session = clean_db
    t0 = datetime(2026, 6, 1, tzinfo=UTC)
    riser = _entity(session, "riser", created=t0)
    faller = _entity(session, "faller", created=t0)
    day = date(2026, 6, 10)
    prev = date(2026, 6, 9)
    _state(session, riser, prev, "simmering")
    _state(session, riser, day, "breakout")  # ↑
    _state(session, faller, prev, "accelerating")
    _state(session, faller, day, "fading")  # ↓
    session.execute(
        text(
            "INSERT INTO maturity_promotions (entity_id, stage, promoted_at) "
            "VALUES (:e, 'distribution', :d)"
        ),
        {"e": riser, "d": datetime(2026, 6, 10, 12, tzinfo=UTC)},
    )
    session.flush()

    stats = compute_changes(session, datetime(2026, 6, 10, 23, tzinfo=UTC))
    assert stats.state_up == 1 and stats.state_down == 1 and stats.promotion == 1
    rows = (
        session.execute(
            text("SELECT kind, text FROM changes_daily WHERE day = :d ORDER BY kind"), {"d": day}
        )
        .mappings()
        .all()
    )
    kinds = {r["kind"] for r in rows}
    assert {"state_up", "state_down", "promotion"} <= kinds
    up = next(r for r in rows if r["kind"] == "state_up")
    assert "breakout" in up["text"] and "↑" in up["text"]


def test_changes_is_rerunnable(clean_db: Session) -> None:
    session = clean_db
    t0 = datetime(2026, 6, 1, tzinfo=UTC)
    e = _entity(session, "e", created=t0)
    _state(session, e, date(2026, 6, 9), "dormant")
    _state(session, e, date(2026, 6, 10), "simmering")
    session.flush()
    when = datetime(2026, 6, 10, 23, tzinfo=UTC)
    compute_changes(session, when)
    session.flush()
    compute_changes(session, when)  # second run replaces, not appends
    session.flush()
    n = session.execute(
        text("SELECT COUNT(*) FROM changes_daily WHERE day = :d"), {"d": date(2026, 6, 10)}
    ).scalar_one()
    assert n == 1


def test_changes_new_entity_survival(clean_db: Session) -> None:
    session = clean_db
    born = datetime(2026, 6, 3, tzinfo=UTC)  # exactly 7 days before the run day
    e = _entity(session, "survivor", created=born)
    _attach(session, e, born)
    session.flush()
    stats = compute_changes(session, datetime(2026, 6, 10, 12, tzinfo=UTC))
    assert stats.new_entity == 1


# --- momentum calibration (doc 09 §3) ---------------------------------------


def test_breakout_survival_ratio(clean_db: Session) -> None:
    session = clean_db
    as_of = datetime(2026, 6, 1, tzinfo=UTC)
    old = as_of - timedelta(days=120)  # first breakout ≥90d ago → in the cohort
    survivor = _entity(session, "surv", created=old)
    died = _entity(session, "died", created=old)
    _state(session, survivor, old.date(), "breakout")
    _state(session, survivor, (as_of - timedelta(days=1)).date(), "accelerating")  # alive
    _state(session, died, old.date(), "breakout")
    _state(session, died, (as_of - timedelta(days=1)).date(), "dormant")  # dead
    session.flush()

    stats = run_momentum_review(session, as_of)
    assert stats.breakout_n == 2
    assert stats.breakout_survival == pytest.approx(0.5)
    row = (
        session.execute(
            text(
                "SELECT value, sample_n FROM calibration_snapshots "
                "WHERE metric = 'breakout_survival'"
            )
        )
        .mappings()
        .one()
    )
    assert row["sample_n"] == 2


def test_calibration_handles_empty_cohort(clean_db: Session) -> None:
    session = clean_db
    stats = run_momentum_review(session, datetime(2026, 6, 1, tzinfo=UTC))
    assert stats.breakout_survival is None and stats.breakout_n == 0
    assert any("breakout" in n for n in stats.notes)


# --- brief forward-scoring + A-7 auto-eval (doc 09 §2) ----------------------


def test_system_observable_auto_eval_on_track_and_counter(clean_db: Session) -> None:
    session = clean_db
    published = datetime(2026, 1, 1, tzinfo=UTC)
    now = datetime(2026, 5, 1, tzinfo=UTC)  # 120d later, past the 'quarters' horizon
    e = _entity(session, "vllm", created=published)
    # metric fell over the window; a thesis predicting "down" is on track.
    _metric(session, e, "hf_downloads_30d", published.date(), 1000)
    _metric(session, e, "hf_downloads_30d", now.date(), 400)
    bid = _brief(
        session,
        e,
        created=published,
        observables=[
            {
                "statement": "downloads fall",
                "source": "system",
                "system_metric": "hf_downloads_30d",
                "horizon": "quarters",
                "direction_if_thesis_holds": "down",
            },
            {
                "statement": "usage rises",
                "source": "system",
                "system_metric": "hf_downloads_30d",
                "horizon": "quarters",
                "direction_if_thesis_holds": "up",
            },
            {
                "statement": "operator reads the 10-Q",
                "source": "manual",
                "system_metric": None,
                "horizon": "quarters",
                "direction_if_thesis_holds": "down",
            },
        ],
    )
    session.flush()

    packet = assemble_score_packet(session, bid, now=now)
    by_stmt = {ev.statement: ev.status for ev in packet.observable_evals}
    assert by_stmt["downloads fall"] == "on_track"  # metric went down, thesis said down
    assert by_stmt["usage rises"] == "counter"  # metric went down, thesis said up
    assert by_stmt["operator reads the 10-Q"] == "operator_judgment"
    assert "hf_downloads_30d" in packet.metric_history


def test_system_observable_too_early_when_flat_and_recent(clean_db: Session) -> None:
    session = clean_db
    published = datetime(2026, 6, 1, tzinfo=UTC)
    now = published + timedelta(days=10)  # well within the 'quarters' (90d) horizon
    e = _entity(session, "proj", created=published)
    _metric(session, e, "gh_stars", published.date(), 100)
    _metric(session, e, "gh_stars", now.date(), 101)  # ~flat
    bid = _brief(
        session,
        e,
        created=published,
        observables=[
            {
                "statement": "stars accelerate",
                "source": "system",
                "system_metric": "gh_stars",
                "horizon": "quarters",
                "direction_if_thesis_holds": "up",
            }
        ],
    )
    session.flush()
    packet = assemble_score_packet(session, bid, now=now)
    assert packet.observable_evals[0].status == "too_early"


def test_record_score_upserts(clean_db: Session) -> None:
    session = clean_db
    t0 = datetime(2026, 1, 1, tzinfo=UTC)
    e = _entity(session, "e", created=t0)
    bid = _brief(
        session,
        e,
        created=t0,
        observables=[
            {
                "statement": "x",
                "source": "manual",
                "system_metric": None,
                "horizon": "quarters",
                "direction_if_thesis_holds": "down",
            }
        ],
    )
    session.flush()
    record_score(
        session,
        bid,
        materialized="partial",
        falsifier_tripped=False,
        verdict="early but plausible",
        counter_was_better=False,
    )
    record_score(
        session,
        bid,
        materialized="yes",
        falsifier_tripped=True,
        falsifier_observable="x",
        verdict="materialized",
        counter_was_better=True,
    )
    session.flush()
    rows = (
        session.execute(
            text(
                "SELECT materialized, falsifier_tripped, notes FROM brief_scores "
                "WHERE brief_id = :b"
            ),
            {"b": bid},
        )
        .mappings()
        .all()
    )
    assert len(rows) == 1  # upsert, not append
    assert rows[0]["materialized"] == "yes" and rows[0]["falsifier_tripped"] is True
    assert json.loads(rows[0]["notes"])["counter_was_better"] is True

    # the assembler surfaces the recorded score back on the packet
    packet = assemble_score_packet(session, bid, now=t0 + timedelta(days=1))
    assert packet.existing_score is not None and packet.existing_score["materialized"] == "yes"


def test_record_score_rejects_bad_materialized(clean_db: Session) -> None:
    session = clean_db
    t0 = datetime(2026, 1, 1, tzinfo=UTC)
    e = _entity(session, "e", created=t0)
    bid = _brief(
        session,
        e,
        created=t0,
        observables=[
            {
                "statement": "x",
                "source": "manual",
                "system_metric": None,
                "horizon": "quarters",
                "direction_if_thesis_holds": "down",
            }
        ],
    )
    session.flush()
    with pytest.raises(ValueError):
        record_score(session, bid, materialized="maybe")
