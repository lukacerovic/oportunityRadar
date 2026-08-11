"""Wave Radar on synthetic fixtures (``WAVE_PLAN.md``).

The positive fixture is the acceptance test and reproduces the exact shape of the known finding in
``AGENT_GUARDRAIL_WAVE.md``: six young entities, **none of which points at any other**, each
carrying a semantic edge to a *different* outside neighbour, spanning two categories that map to
two different themes. Any implementation that clusters on direct edges, or on shared category,
fails it.

The negative fixtures cover each independence check, because a convincing false wave — five repos
from one team — is worse than no wave at all.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta

import pytest
from sqlalchemy import text
from sqlalchemy.orm import Session

from seismo.models import (
    Entity,
    EntityCategoryHistory,
    EntityGraphEdge,
    EntityLink,
    EntitySemanticEdge,
    RawEvent,
)
from seismo.waves.continuity import match_wave
from seismo.waves.detect import normalize_label, run_waves
from seismo.waves.observers import find_for_wave, search_terms

AS_OF = datetime(2026, 7, 20, 23, 59, 59, tzinfo=UTC)
FIRST_SEEN = datetime(2026, 7, 2, tzinfo=UTC)  # 18 days before AS_OF, inside the 30d window


@pytest.fixture(autouse=True)
def _isolated(clean_db: Session) -> Session:
    return clean_db


def _entity(
    session: Session,
    name: str,
    *,
    category: str | None = "agent-framework",
    first_seen: datetime = FIRST_SEEN,
    github: str | None = None,
    entity_type: str = "project",
) -> int:
    ent = Entity(
        entity_type=entity_type,
        canonical_name=name,
        category=category,
        created_at=first_seen,
        attrs={"anchors": {"github": github}} if github else {},
    )
    session.add(ent)
    session.flush()
    # Age comes from the earliest ATTACHED evidence, not entities.created_at, so every fixture
    # entity needs a real event or entity_facts will not see it at all.
    ev = RawEvent(
        source="github",
        source_event_uid=f"fixture:{name}",
        event_type="repo_snapshot",
        occurred_at=first_seen,
        payload={"name": name},
    )
    session.add(ev)
    session.flush()
    session.add(EntityLink(entity_id=ent.id, raw_event_id=ev.id, rule="attach", confidence=1.0))
    if category:
        # Cohorts read category through category_asof (doc 13 A-2), i.e. from the history table —
        # entities.category alone is invisible to entity_facts.
        session.add(
            EntityCategoryHistory(entity_id=ent.id, category=category, effective_at=first_seen)
        )
    session.flush()
    return int(ent.id)


def _semantic(session: Session, src: int, dst_label: str, *, dst_id: int | None = None) -> None:
    session.add(
        EntitySemanticEdge(
            src_entity_id=src,
            dst_entity_id=dst_id,
            src_label=f"e{src}",
            dst_label=dst_label,
            relation="semantically_similar_to",
            confidence="high",
            confidence_score=0.9,
            model="fixture",
        )
    )
    session.flush()


def _guardrail_wave(session: Session) -> list[int]:
    """The known finding, reproduced. Members share NO edges with each other; each points at its own
    neighbour, and those neighbours all sit in one category. Two member categories, two themes."""
    members = [
        _entity(session, "coder_eval", github="uipath/coder_eval"),
        _entity(session, "termaxa", github="termaxa/termaxa"),
        _entity(session, "r3", github="hyperlogue/r3"),
        _entity(session, "open-record-replay", github="video-db/open-record-replay"),
        _entity(session, "verbatimeter", category="rag-framework", github="pob/verbatimeter"),
        _entity(session, "postern", category="rag-framework", github="skyphusion/postern"),
    ]
    # Each neighbour is a distinct entity in a shared category — the second link route.
    for i, m in enumerate(members):
        neighbour = _entity(
            session,
            f"neighbour-{i}",
            category="guardrails",
            first_seen=FIRST_SEEN - timedelta(days=400),  # old, so it is never a candidate itself
            github=f"nb{i}/neighbour-{i}",
        )
        _semantic(session, m, f"neighbour-{i}", dst_id=neighbour)
    return members


def _wave_rows(session: Session) -> list[tuple[int, int]]:
    return session.execute(
        text(
            """
            SELECT w.id, count(m.entity_id)
            FROM wave_clusters w LEFT JOIN wave_members m ON m.wave_id = w.id
            GROUP BY w.id ORDER BY w.id
            """
        )
    ).all()


# --- the acceptance test ----------------------------------------------------


def test_detects_the_guardrail_wave(db_session: Session) -> None:
    """Six independent members, zero edges between them, two categories → exactly one wave."""
    members = _guardrail_wave(db_session)

    stats = run_waves(db_session, AS_OF)

    assert stats.waves_written == 1, stats.as_note()
    rows = _wave_rows(db_session)
    assert len(rows) == 1
    wave_id, member_count = rows[0]
    assert member_count == len(members) == 6

    stored = set(
        db_session.execute(
            text("SELECT entity_id FROM wave_members WHERE wave_id = :w"), {"w": wave_id}
        ).scalars()
    )
    assert stored == set(members)


def test_wave_spans_two_categories(db_session: Session) -> None:
    """Category is a weak prior, never the grouping key — the known wave crossed two themes."""
    _guardrail_wave(db_session)
    run_waves(db_session, AS_OF)

    components = db_session.execute(text("SELECT components FROM wave_clusters")).scalar_one()
    assert set(components["categories"]) == {"agent-framework", "rag-framework"}


def test_members_carry_no_edges_to_each_other(db_session: Session) -> None:
    """Guards the fixture itself: if members ever link directly, the test stops proving anything."""
    members = _guardrail_wave(db_session)
    direct = db_session.execute(
        text(
            """
            SELECT count(*) FROM entity_semantic_edges
            WHERE src_entity_id = ANY(:ids) AND dst_entity_id = ANY(:ids)
            """
        ),
        {"ids": members},
    ).scalar_one()
    assert direct == 0


# --- independence: each check gets a negative fixture -----------------------


def test_shared_owner_collapses_to_one_member(db_session: Session) -> None:
    """Five repos under one GitHub owner are one team's product line, not convergence."""
    for i in range(5):
        e = _entity(db_session, f"svc-{i}", github=f"acme/svc-{i}")
        neighbour = _entity(
            db_session,
            f"nb-{i}",
            category="guardrails",
            first_seen=FIRST_SEEN - timedelta(days=400),
        )
        _semantic(db_session, e, "shared-neighbour", dst_id=neighbour)

    stats = run_waves(db_session, AS_OF)

    assert stats.waves_written == 0
    assert stats.below_min_members == 1
    assert stats.collapsed_members == 4  # one representative survives, four absorbed


def test_shared_author_collapses_members(db_session: Session) -> None:
    """A shared person entity means one team — even with no owner or dependency overlap."""
    members = _guardrail_wave(db_session)
    person = _entity(
        db_session, "one-dev", entity_type="person", category=None, first_seen=FIRST_SEEN
    )
    # Three of the six were built by the same human.
    for m in members[:3]:
        db_session.add(
            EntityGraphEdge(src_entity_id=m, dst_entity_id=person, edge_type="built_by", weight=1.0)
        )
    db_session.flush()

    stats = run_waves(db_session, AS_OF)

    # 6 members - 2 absorbed = 4, still at the minimum, so a wave survives but is smaller.
    assert stats.collapsed_members == 2
    rows = _wave_rows(db_session)
    assert rows and rows[0][1] == 4


def test_dependency_chain_is_not_a_wave(db_session: Session) -> None:
    """An ecosystem around one project is not parallel invention."""
    members = _guardrail_wave(db_session)
    for a, b in zip(members, members[1:], strict=False):
        db_session.add(
            EntityGraphEdge(src_entity_id=a, dst_entity_id=b, edge_type="depends_on", weight=1.0)
        )
    db_session.flush()

    stats = run_waves(db_session, AS_OF)

    assert stats.waves_written == 0
    assert stats.below_min_members == 1


def test_independence_records_failed_checks(db_session: Session) -> None:
    """Trust comes from seeing what was excluded — failed checks are stored, not just applied."""
    members = _guardrail_wave(db_session)
    person = _entity(
        db_session, "one-dev", entity_type="person", category=None, first_seen=FIRST_SEEN
    )
    for m in members[:2]:
        db_session.add(
            EntityGraphEdge(src_entity_id=m, dst_entity_id=person, edge_type="built_by", weight=1.0)
        )
    db_session.flush()
    run_waves(db_session, AS_OF)

    rows = (
        db_session.execute(
            text("SELECT independence FROM wave_members WHERE independence -> 'conflicts' != '[]'")
        )
        .scalars()
        .all()
    )
    assert rows, "a collapsed member's conflict must survive into the audit row"
    assert rows[0]["conflicts"][0]["kind"] == "shared_person"


# --- windows and thresholds -------------------------------------------------


def test_entities_outside_the_window_are_not_candidates(db_session: Session) -> None:
    """A cluster is about things that appeared *together*; old entities are not part of it."""
    old = FIRST_SEEN - timedelta(days=200)
    for i in range(6):
        e = _entity(db_session, f"old-{i}", first_seen=old, github=f"o{i}/old-{i}")
        neighbour = _entity(
            db_session, f"nb-{i}", category="guardrails", first_seen=old - timedelta(days=100)
        )
        _semantic(db_session, e, "shared", dst_id=neighbour)

    stats = run_waves(db_session, AS_OF)

    assert stats.candidates == 0
    assert stats.waves_written == 0


def test_below_minimum_members_is_not_a_wave(db_session: Session) -> None:
    for i in range(3):
        e = _entity(db_session, f"few-{i}", github=f"f{i}/few-{i}")
        neighbour = _entity(
            db_session,
            f"nb-{i}",
            category="guardrails",
            first_seen=FIRST_SEEN - timedelta(days=400),
        )
        _semantic(db_session, e, "shared", dst_id=neighbour)

    stats = run_waves(db_session, AS_OF)

    assert stats.waves_written == 0


# --- continuity across runs -------------------------------------------------


def test_rerun_keeps_the_same_wave_and_first_seen(db_session: Session) -> None:
    """Recomputed daily, a wave must keep its id and birth date or the record becomes churn."""
    _guardrail_wave(db_session)
    run_waves(db_session, AS_OF)
    first = db_session.execute(text("SELECT id, first_seen FROM wave_clusters")).one()

    run_waves(db_session, AS_OF + timedelta(days=1))
    after = db_session.execute(text("SELECT id, first_seen FROM wave_clusters")).all()

    assert len(after) == 1
    assert after[0][0] == first[0]
    assert after[0][1] == first[1]


def test_new_member_appends_without_resetting_first_seen(db_session: Session) -> None:
    _guardrail_wave(db_session)
    run_waves(db_session, AS_OF)
    original = db_session.execute(text("SELECT id, first_seen FROM wave_clusters")).one()

    later = FIRST_SEEN + timedelta(days=10)
    newcomer = _entity(db_session, "latecomer", first_seen=later, github="new/latecomer")
    neighbour = _entity(
        db_session, "nb-late", category="guardrails", first_seen=FIRST_SEEN - timedelta(days=400)
    )
    _semantic(db_session, newcomer, "neighbour-0", dst_id=neighbour)

    run_waves(db_session, AS_OF + timedelta(days=1))

    rows = _wave_rows(db_session)
    assert len(rows) == 1
    assert rows[0][0] == original[0]
    assert rows[0][1] == 7
    assert db_session.execute(text("SELECT first_seen FROM wave_clusters")).scalar() == original[1]
    joined = db_session.execute(
        text("SELECT joined_at FROM wave_members WHERE entity_id = :e"), {"e": newcomer}
    ).scalar()
    assert joined == later.date()


def test_match_wave_uses_the_smaller_set(db_session: Session) -> None:
    """A wave that doubles in size must still match its earlier, smaller self."""
    existing = {1: {10, 11, 12, 13}}
    assert match_wave({10, 11, 12, 13, 20, 21, 22, 23}, existing) == 1
    assert match_wave({90, 91, 92, 93}, existing) is None


# --- determinism ------------------------------------------------------------


def test_two_runs_at_the_same_as_of_agree(db_session: Session) -> None:
    _guardrail_wave(db_session)
    a = run_waves(db_session, AS_OF)
    strength_a = db_session.execute(text("SELECT strength FROM wave_clusters")).scalar()
    b = run_waves(db_session, AS_OF)
    strength_b = db_session.execute(text("SELECT strength FROM wave_clusters")).scalar()

    assert (a.waves_written, a.candidates) == (b.waves_written, b.candidates)
    assert strength_a == strength_b


# --- observers --------------------------------------------------------------


def test_finds_an_earlier_mention_and_its_lead(db_session: Session) -> None:
    """The product's central claim: a dated mention that predates detection, with its author."""
    _guardrail_wave(db_session)
    run_waves(db_session, AS_OF)
    wave_id, detected = db_session.execute(text("SELECT id, first_seen FROM wave_clusters")).one()

    said_at = datetime(2026, 6, 14, 12, 0, tzinfo=UTC)
    db_session.add(
        RawEvent(
            source="hn",
            source_event_uid="hn-early",
            event_type="story",
            occurred_at=said_at,
            payload={
                "author": "early_bird",
                "title": "Nobody is talking about verbatimeter and grounding checks",
                "story_text": "",
            },
        )
    )
    db_session.flush()

    written = find_for_wave(db_session, wave_id, AS_OF)

    assert written >= 1
    row = db_session.execute(
        text(
            "SELECT author_handle, lead_days, observed_at FROM wave_observations"
            " WHERE wave_id = :w ORDER BY lead_days DESC LIMIT 1"
        ),
        {"w": wave_id},
    ).one()
    assert row[0] == "early_bird"
    assert row[1] == (detected - said_at.date()).days
    assert row[1] > 0


def test_mentions_after_as_of_are_invisible(db_session: Session) -> None:
    """Invariant 2 — replaying a past day must not see text published later."""
    _guardrail_wave(db_session)
    run_waves(db_session, AS_OF)
    wave_id = db_session.execute(text("SELECT id FROM wave_clusters")).scalar_one()

    db_session.add(
        RawEvent(
            source="hn",
            source_event_uid="hn-future",
            event_type="story",
            occurred_at=AS_OF + timedelta(days=30),
            payload={"author": "hindsight", "title": "verbatimeter was obvious all along"},
        )
    )
    db_session.flush()

    find_for_wave(db_session, wave_id, AS_OF)

    authors = set(db_session.execute(text("SELECT author_handle FROM wave_observations")).scalars())
    assert "hindsight" not in authors


def test_substring_matches_are_not_mentions(db_session: Session) -> None:
    """'r3' inside 'chair3d' is not a mention; substring matching would fake foresight."""
    _guardrail_wave(db_session)
    run_waves(db_session, AS_OF)
    wave_id = db_session.execute(text("SELECT id FROM wave_clusters")).scalar_one()

    db_session.add(
        RawEvent(
            source="hn",
            source_event_uid="hn-noise",
            event_type="story",
            occurred_at=datetime(2026, 6, 1, tzinfo=UTC),
            payload={"author": "noise", "title": "Announcing chair3designer and posterny things"},
        )
    )
    db_session.flush()

    find_for_wave(db_session, wave_id, AS_OF)

    authors = set(db_session.execute(text("SELECT author_handle FROM wave_observations")).scalars())
    assert "noise" not in authors


def test_short_terms_are_not_searched() -> None:
    """A three-letter name matches half of Hacker News; a false earliest mention back-dates the
    record, which is the one failure this feature cannot afford."""
    assert search_terms("r3", "hyperlogue/r3") == []
    assert search_terms("verbatimeter", "pob/verbatimeter") == ["verbatimeter"]


def test_normalize_label_collapses_case_and_space() -> None:
    assert normalize_label("  LangChain  ") == normalize_label("langchain")


# --- outcomes ---------------------------------------------------------------


def test_outcome_is_unmeasurable_without_usage_metrics(db_session: Session) -> None:
    """npm is not collected and PyPI is Python-only, so a wave can genuinely have nothing to
    measure — and that must never be recorded as ``faded``."""
    from seismo.waves.outcomes import evaluate_wave

    _guardrail_wave(db_session)
    run_waves(db_session, AS_OF)
    wave_id = db_session.execute(text("SELECT id FROM wave_clusters")).scalar_one()

    evaluate_wave(db_session, wave_id, AS_OF + timedelta(days=200))

    verdicts = set(
        db_session.execute(
            text("SELECT verdict FROM wave_outcomes WHERE wave_id = :w"), {"w": wave_id}
        ).scalars()
    )
    assert verdicts == {"unmeasurable"}


def test_outcome_beats_its_cohort(db_session: Session) -> None:
    """Cohort-relative, never absolute: the wave must out-grow its own peer group to take hold."""
    from seismo.waves.outcomes import evaluate_wave

    members = _guardrail_wave(db_session)
    run_waves(db_session, AS_OF)
    wave_id = db_session.execute(text("SELECT id FROM wave_clusters")).scalar_one()

    detected: date = db_session.execute(text("SELECT first_seen FROM wave_clusters")).scalar_one()
    end = detected + timedelta(days=90)

    def metric(entity_id: int, day: date, value: float) -> None:
        db_session.execute(
            text(
                "INSERT INTO entity_metrics_daily (entity_id, metric, day, value)"
                " VALUES (:e,'pypi_downloads_7d',:d,:v)"
                " ON CONFLICT (entity_id, metric, day) DO UPDATE SET value = EXCLUDED.value"
            ),
            {"e": entity_id, "d": day, "v": value},
        )

    for m in members:
        metric(m, detected, 40)
        metric(m, end, 31_000)  # ×775

    # Peers in the same cohort grow modestly. They must be same-age and same-category to land in
    # the members' cohort key at all.
    for i in range(10):
        peer = _entity(db_session, f"peer-{i}", github=f"p{i}/peer-{i}")
        metric(peer, detected, 100)
        metric(peer, end, 210)  # ×2.1
    db_session.flush()

    evaluate_wave(db_session, wave_id, AS_OF + timedelta(days=200))

    row = db_session.execute(
        text(
            "SELECT verdict, wave_growth, cohort_growth, percentile FROM wave_outcomes"
            " WHERE wave_id = :w AND metric = 'pypi_downloads_7d'"
        ),
        {"w": wave_id},
    ).one()
    assert row[0] == "took_hold"
    assert row[1] > row[2]
    assert row[3] == pytest.approx(1.0)


def test_outcome_before_the_horizon_is_never_a_verdict(db_session: Session) -> None:
    """A reading taken before the horizon elapses is data, not a judgment."""
    from seismo.waves.outcomes import evaluate_wave

    _guardrail_wave(db_session)
    run_waves(db_session, AS_OF)
    wave_id = db_session.execute(text("SELECT id FROM wave_clusters")).scalar_one()

    evaluate_wave(db_session, wave_id, AS_OF)  # only ~18 days in

    rows = db_session.execute(
        text("SELECT verdict, detail FROM wave_outcomes WHERE wave_id = :w"), {"w": wave_id}
    ).all()
    assert rows
    assert all(r[0] == "unmeasurable" for r in rows)
    assert all(r[1]["horizon_reached"] is False for r in rows)


# --- facets: theme is a filter over whole waves, never a parent -------------


def test_categories_for_theme_maps_through_the_vocabulary() -> None:
    from seismo.waves.facets import categories_for_theme

    assert "agent-framework" in categories_for_theme("agent tooling")
    assert "rag-framework" in categories_for_theme("retrieval & memory")


def test_unknown_theme_matches_nothing_not_everything() -> None:
    """A typo must not silently return an unfiltered list the reader believes is filtered."""
    from seismo.waves.facets import categories_for_theme

    assert categories_for_theme("not-a-real-theme") == []


def test_a_wave_can_touch_two_themes(db_session: Session) -> None:
    """The known convergence spanned agent-framework and rag-framework — two different themes.
    Nesting waves under a category would have cut it in half at the navigation layer."""
    from seismo.waves.facets import wave_themes

    _guardrail_wave(db_session)
    run_waves(db_session, AS_OF)
    wave_id = db_session.execute(text("SELECT id FROM wave_clusters")).scalar_one()

    themes = wave_themes(db_session, [wave_id])

    assert themes[wave_id] == ["agent tooling", "retrieval & memory"]


def test_api_theme_filter_returns_the_wave_under_both_themes(db_session: Session) -> None:
    from fastapi.testclient import TestClient

    from seismo.api.app import app, get_session

    _guardrail_wave(db_session)
    run_waves(db_session, AS_OF)
    app.dependency_overrides[get_session] = lambda: db_session
    client = TestClient(app)
    try:
        agent = client.get("/waves", params={"theme": "agent tooling"}).json()
        rag = client.get("/waves", params={"theme": "retrieval & memory"}).json()
        missing = client.get("/waves", params={"theme": "hardware & systems"}).json()
        bogus = client.get("/waves", params={"theme": "izmisljeno"}).json()
    finally:
        app.dependency_overrides.clear()

    assert len(agent) == 1
    assert agent[0]["id"] == rag[0]["id"], "the same wave must appear under both of its themes"
    assert agent[0]["themes"] == ["agent tooling", "retrieval & memory"]
    assert missing == []
    assert bogus == []


def test_api_lead_and_verdict_filters_compose(db_session: Session) -> None:
    from fastapi.testclient import TestClient

    from seismo.api.app import app, get_session

    _guardrail_wave(db_session)
    run_waves(db_session, AS_OF)
    wave_id = db_session.execute(text("SELECT id FROM wave_clusters")).scalar_one()
    db_session.add(
        RawEvent(
            source="hn",
            source_event_uid="hn-lead",
            event_type="story",
            occurred_at=datetime(2026, 6, 14, tzinfo=UTC),
            payload={"author": "early_bird", "title": "verbatimeter is the interesting one"},
        )
    )
    db_session.flush()
    find_for_wave(db_session, wave_id, AS_OF)

    app.dependency_overrides[get_session] = lambda: db_session
    client = TestClient(app)
    try:
        near = client.get("/waves", params={"min_lead": 14}).json()
        far = client.get("/waves", params={"min_lead": 90}).json()
        ungraded = client.get("/waves", params={"verdict": "ungraded"}).json()
        took_hold = client.get("/waves", params={"verdict": "took_hold"}).json()
    finally:
        app.dependency_overrides.clear()

    assert len(near) == 1
    assert far == []
    assert len(ungraded) == 1, "no outcome has been evaluated, so the wave is ungraded"
    assert took_hold == []
