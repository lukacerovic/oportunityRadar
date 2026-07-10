"""Stage 3 — Trajectory (doc 06). Pure-function tests of the state machine + DB-backed tests of
snapshot metrics, cohort percentiles, the maturity ladder, cold-start warm-up, and as-of purity.

The DB tests run on ``clean_db`` (a rolled-back, emptied transaction) so they exercise real SQL —
``ON CONFLICT`` upserts, window-shaped reads, the recursive-CTE as-of helpers — against synthetic
cohorts, exactly as doc 06 §6 requires.
"""

from __future__ import annotations

import itertools
from datetime import UTC, date, datetime, timedelta

from sqlalchemy import text
from sqlalchemy.orm import Session

from seismo.trajectory.cohorts import age_bucket
from seismo.trajectory.metrics import run_snapshot
from seismo.trajectory.score import run_score
from seismo.trajectory.states import raw_tier, replay
from seismo.trajectory.velocity import DaySignal, _percent_ranks

_UID = itertools.count(1)


# --- synthetic data helpers -------------------------------------------------


def _entity(session: Session, name: str, *, etype: str = "project", created: datetime) -> int:
    row = session.execute(
        text(
            """
            INSERT INTO entities (entity_type, canonical_name, created_at, attrs)
            VALUES (:t, :n, :c, '{}') RETURNING id
            """
        ),
        {"t": etype, "n": name, "c": created},
    ).scalar_one()
    return int(row)


def _event(
    session: Session,
    entity_id: int,
    *,
    source: str,
    event_type: str,
    occurred: datetime,
    payload: dict,
) -> int:
    uid = f"test:{next(_UID)}"
    event_id = session.execute(
        text(
            """
            INSERT INTO raw_events (source, source_event_uid, event_type, occurred_at, payload)
            VALUES (:s, :u, :et, :o, CAST(:p AS JSONB)) RETURNING id
            """
        ),
        {"s": source, "u": uid, "et": event_type, "o": occurred, "p": _json(payload)},
    ).scalar_one()
    session.execute(
        text(
            """
            INSERT INTO entity_links
                (entity_id, raw_event_id, rule, confidence, evidence_occurred_at)
            VALUES (:e, :ev, 'attach', 1.0, :o)
            """
        ),
        {"e": entity_id, "ev": event_id, "o": occurred},
    )
    return int(event_id)


def _json(value: dict) -> str:
    import json

    return json.dumps(value)


def _daily_repo(session: Session, entity_id: int, *, start: datetime, days: int, stars_fn) -> None:
    """Emit one ``repo_snapshot`` per day (keeps the entity active + drives gh_stars)."""
    for d in range(days):
        _event(
            session,
            entity_id,
            source="github",
            event_type="repo_snapshot",
            occurred=start + timedelta(days=d),
            payload={"stars": stars_fn(d), "forks": 0},
        )


def _states_at(session: Session, day: date) -> dict[int, str]:
    rows = session.execute(
        text("SELECT entity_id, state FROM momentum_states WHERE day = :d"), {"d": day}
    ).all()
    return {e: s for e, s in rows}


# --- pure state-machine tests -----------------------------------------------


def test_age_bucket_boundaries() -> None:
    assert age_bucket(0) == "0-30d"
    assert age_bucket(30) == "0-30d"
    assert age_bucket(31) == "31-90d"
    assert age_bucket(365) == "91-365d"
    assert age_bucket(366) == "365d+"


def test_percent_ranks_sql_semantics() -> None:
    # ties share the lower rank; the max is 1.0; a lone value is 0.0.
    from decimal import Decimal as D

    ranks = _percent_ranks([D(0), D(0), D(0), D(10)])
    assert ranks == [0.0, 0.0, 0.0, 1.0]
    assert _percent_ranks([D(5)]) == [0.0]


def test_raw_tier_conditions() -> None:
    breakout = DaySignal(p=0.99, count_60=1, count_80=1, count_95=1, breadth=2)
    assert raw_tier(breakout, promo_30d=0, active=True) == 3
    # breadth gate not met -> falls back to whatever velocity supports (simmering here).
    thin = DaySignal(p=0.99, count_60=1, count_80=0, count_95=1, breadth=1)
    assert raw_tier(thin, promo_30d=0, active=True) == 1
    # two promotions alone = breakout.
    assert raw_tier(DaySignal(), promo_30d=2, active=True) == 3
    # inactive is always dormant.
    assert raw_tier(breakout, promo_30d=2, active=False) == 0


def test_hysteresis_promotion_needs_two_days() -> None:
    start = date(2024, 1, 1)
    # simmering-qualifying signal every day; event daily so active is true.
    sig = DaySignal(p=0.7, count_60=1, cohort_n=8)
    signals = {start + timedelta(days=i): sig for i in range(4)}
    event_days = [start + timedelta(days=i) for i in range(4)]
    out = replay(start, start + timedelta(days=3), signals, event_days, [])
    # day 0: entry condition seen once -> still dormant; day 1: held 2 days -> simmering.
    assert out[start].state == "dormant"
    assert out[start + timedelta(days=1)].state == "simmering"


def test_hysteresis_demotion_needs_seven_days() -> None:
    start = date(2024, 1, 1)
    hot = DaySignal(p=0.7, count_60=1, cohort_n=8)
    cold = DaySignal(p=0.1, cohort_n=8)
    days = [start + timedelta(days=i) for i in range(12)]
    signals = {d: (hot if i < 3 else cold) for i, d in enumerate(days)}
    out = replay(start, days[-1], signals, days, [])
    # simmering by day 1; stays simmering through the 7-day exit hold, drops after.
    assert out[days[2]].state == "simmering"
    assert out[days[8]].state == "simmering"  # exit condition held 6 days, not yet 7
    assert out[days[9]].state in ("dormant", "fading")  # 7th day of exit -> demoted


def test_provisional_caps_emitted_state_at_simmering() -> None:
    start = date(2024, 1, 1)
    # breakout-strength inputs but a thin (provisional) cohort.
    sig = DaySignal(
        p=0.99, count_60=1, count_80=2, count_95=1, breadth=2, provisional=True, cohort_n=3
    )
    days = [start + timedelta(days=i) for i in range(4)]
    out = replay(start, days[-1], {d: sig for d in days}, days, [])
    final = out[days[-1]]
    assert final.state == "simmering", "provisional cohort must not manufacture a breakout"
    assert final.inputs["provisional"] is True
    assert final.inputs["smoothed_tier"] == 3  # true tier is preserved underneath the cap


def test_fading_on_inactivity() -> None:
    start = date(2024, 1, 1)
    hot = DaySignal(p=0.7, count_60=1, cohort_n=8)
    # active + hot for 3 days, then no events at all for 40 days.
    signals = {start + timedelta(days=i): hot for i in range(3)}
    event_days = [start + timedelta(days=i) for i in range(3)]
    out = replay(start, start + timedelta(days=40), signals, event_days, [])
    assert out[start + timedelta(days=2)].state == "simmering"
    assert out[start + timedelta(days=40)].state == "fading"


# --- snapshot metric tests --------------------------------------------------


def test_counter_forward_fills_up_to_three_days(clean_db: Session) -> None:
    session = clean_db
    t0 = datetime(2024, 1, 1, tzinfo=UTC)
    eid = _entity(session, "repo", created=t0)
    _event(
        session,
        eid,
        source="github",
        event_type="repo_snapshot",
        occurred=t0,
        payload={"stars": 100},
    )
    # next observation 5 days later -> fill days 1,2,3 (not 4), then day 5 observed.
    _event(
        session,
        eid,
        source="github",
        event_type="repo_snapshot",
        occurred=t0 + timedelta(days=5),
        payload={"stars": 160},
    )
    session.flush()
    run_snapshot(session, t0 + timedelta(days=6))

    rows = dict(
        session.execute(
            text(
                "SELECT day, value FROM entity_metrics_daily "
                "WHERE entity_id = :e AND metric = 'gh_stars' ORDER BY day"
            ),
            {"e": eid},
        ).all()
    )
    days = {d.isoformat(): int(v) for d, v in rows.items()}
    assert days["2024-01-01"] == 100
    assert days["2024-01-02"] == 100 and days["2024-01-04"] == 100  # forward-filled
    assert "2024-01-05" not in days  # gap wider than 3 days leaves a hole
    assert days["2024-01-06"] == 160


def test_level_metric_is_never_forward_filled(clean_db: Session) -> None:
    session = clean_db
    t0 = datetime(2024, 1, 1, tzinfo=UTC)
    eid = _entity(session, "model", etype="model", created=t0)
    _event(
        session,
        eid,
        source="hf",
        event_type="model_snapshot",
        occurred=t0,
        payload={"downloads": 5000},
    )
    session.flush()
    run_snapshot(session, t0 + timedelta(days=3))
    rows = session.execute(
        text(
            "SELECT day FROM entity_metrics_daily "
            "WHERE entity_id = :e AND metric = 'hf_downloads_30d'"
        ),
        {"e": eid},
    ).all()
    assert len(rows) == 1, "a level must not be carried forward across days (doc 03 §2.4)"


def test_rolling_and_breadth_metrics(clean_db: Session) -> None:
    session = clean_db
    t0 = datetime(2024, 1, 1, tzinfo=UTC)
    eid = _entity(session, "proj", created=t0)
    _event(session, eid, source="hn", event_type="story", occurred=t0, payload={"points": 40})
    _event(
        session,
        eid,
        source="github",
        event_type="repo_snapshot",
        occurred=t0,
        payload={"stars": 10},
    )
    session.flush()
    run_snapshot(session, t0 + timedelta(days=2))
    # hn_points_7d covers the story for 7 days.
    pts = session.execute(
        text(
            "SELECT value FROM entity_metrics_daily "
            "WHERE entity_id = :e AND metric = 'hn_points_7d' AND day = :d"
        ),
        {"e": eid, "d": t0.date()},
    ).scalar_one()
    assert int(pts) == 40
    # two evidence types active -> breadth 2.
    breadth = session.execute(
        text(
            "SELECT value FROM entity_metrics_daily "
            "WHERE entity_id = :e AND metric = 'evidence_breadth' AND day = :d"
        ),
        {"e": eid, "d": t0.date()},
    ).scalar_one()
    assert int(breadth) == 2


# --- cohort percentile + full pipeline --------------------------------------


def _build_cohort(session: Session, t0: datetime, *, n_members: int, days: int) -> int:
    """A cohort of ``n_members`` flat repos plus one fast riser (returned). The riser also gets an
    HN story so its breadth reaches 2 (the breakout gate)."""
    for i in range(n_members):
        flat = _entity(session, f"flat-{i}", created=t0)
        _daily_repo(session, flat, start=t0, days=days, stars_fn=lambda d: 100)
    riser = _entity(session, "riser", created=t0)
    _daily_repo(session, riser, start=t0, days=days, stars_fn=lambda d: 100 + 60 * d)
    _event(
        session,
        riser,
        source="hn",
        event_type="story",
        occurred=t0 + timedelta(days=1),
        payload={"points": 80},
    )
    session.flush()
    return riser


def test_riser_breaks_out_against_flat_cohort(clean_db: Session) -> None:
    session = clean_db
    t0 = datetime(2024, 1, 1, tzinfo=UTC)
    riser = _build_cohort(session, t0, n_members=8, days=12)  # 9-member cohort, not provisional
    as_of = t0 + timedelta(days=11)
    run_snapshot(session, as_of)
    run_score(session, as_of)

    states = _states_at(session, as_of.date())
    assert states[riser] == "breakout", f"riser should break out, got {states[riser]}"
    flat_states = {s for e, s in states.items() if e != riser}
    assert flat_states == {"dormant"}, "flat peers must stay dormant"
    # riser's qualifying day is non-provisional and records its cohort size.
    inp = session.execute(
        text("SELECT inputs FROM momentum_states WHERE entity_id = :e AND day = :d"),
        {"e": riser, "d": as_of.date()},
    ).scalar_one()
    assert inp["provisional"] is False
    assert inp["cohort_n"] >= 8


def test_thin_cohort_riser_is_provisional_and_capped(clean_db: Session) -> None:
    session = clean_db
    t0 = datetime(2024, 1, 1, tzinfo=UTC)
    riser = _build_cohort(session, t0, n_members=2, days=12)  # 3-member cohort -> provisional
    as_of = t0 + timedelta(days=11)
    run_snapshot(session, as_of)
    run_score(session, as_of)
    state = _states_at(session, as_of.date())[riser]
    inp = session.execute(
        text("SELECT inputs FROM momentum_states WHERE entity_id = :e AND day = :d"),
        {"e": riser, "d": as_of.date()},
    ).scalar_one()
    assert inp["provisional"] is True
    assert state == "simmering", "a thin cohort may not manufacture a breakout (doc 14 §5)"


# --- maturity ladder --------------------------------------------------------


def test_ladder_detects_rungs_with_evidence(clean_db: Session) -> None:
    session = clean_db
    t0 = datetime(2024, 1, 1, tzinfo=UTC)
    eid = _entity(session, "thing", created=t0)
    paper = _event(
        session,
        eid,
        source="arxiv",
        event_type="paper_published",
        occurred=t0,
        payload={"title": "a paper"},
    )
    _event(
        session,
        eid,
        source="github",
        event_type="repo_discovered",
        occurred=t0 + timedelta(days=5),
        payload={"full_name": "org/thing"},
    )
    _event(
        session,
        eid,
        source="github",
        event_type="release_published",
        occurred=t0 + timedelta(days=10),
        payload={"tag": "v1"},
    )
    _event(
        session,
        eid,
        source="pypi",
        event_type="pypi_snapshot",
        occurred=t0 + timedelta(days=15),
        payload={"downloads_7d": 1000},
    )
    session.flush()
    run_score(session, t0 + timedelta(days=20))

    rungs = dict(
        session.execute(
            text("SELECT stage, evidence_event FROM maturity_promotions WHERE entity_id = :e"),
            {"e": eid},
        ).all()
    )
    assert set(rungs) == {"idea_paper", "public_code", "usable_artifact", "distribution"}
    assert rungs["idea_paper"] == paper  # evidenced by the earliest qualifying event


# --- as-of purity (the non-negotiable CI test, doc 06 §5) -------------------


def test_score_is_pure_function_of_events_up_to_asof(clean_db: Session) -> None:
    session = clean_db
    t0 = datetime(2024, 1, 1, tzinfo=UTC)
    riser = _build_cohort(session, t0, n_members=8, days=12)
    as_of = t0 + timedelta(days=8)

    run_snapshot(session, as_of)
    run_score(session, as_of)
    first = _snapshot_of_states(session)

    # Later data arrives (after as_of): a surge of stars and a brand-new entity.
    _daily_repo(
        session, riser, start=t0 + timedelta(days=12), days=6, stars_fn=lambda d: 100000 + d
    )
    newbie = _entity(session, "latecomer", created=t0 + timedelta(days=13))
    _daily_repo(session, newbie, start=t0 + timedelta(days=13), days=5, stars_fn=lambda d: 5000 * d)
    session.flush()

    # Re-run for the SAME as_of: output must be byte-identical (no future leak).
    run_snapshot(session, as_of)
    run_score(session, as_of)
    second = _snapshot_of_states(session)
    assert first == second, "score --as-of D must be identical after later data arrives"
    assert all(day <= as_of.date() for _, day in second), "no state row may exist past as_of"


def _snapshot_of_states(session: Session) -> dict[tuple[int, date], tuple[str, str]]:
    rows = session.execute(
        text("SELECT entity_id, day, state, CAST(inputs AS TEXT) FROM momentum_states")
    ).all()
    return {(e, d): (s, i) for e, d, s, i in rows}
