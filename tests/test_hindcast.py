"""Stage 9 — Hindcast validation harness (doc 11).

Three layers, all on synthetic/small data (the heavy GH Archive backfill is flagged, never run in
tests): the case-YAML format + its validation, each assertion evaluator against hand-seeded pipeline
output, and two end-to-end ``run_hindcast`` replays through the *real* orchestrators — a green
negative-shape run (suppressed + brief-free) and the forced-brief step (mock provider, $0).

The evaluator/format tests run on the fast rollback-only ``db_session`` (they query by specific
entity id / a unique synthetic anchor, so a globally-clean DB is unnecessary and the 733k-row
``clean_db`` DELETE is not worth paying ~19×). The two end-to-end runner tests use ``clean_db`` —
the pipeline replay must see only the synthetic seed, not the dev universe. ``exposure_companies``/
``reach_links`` are global (neither fixture clears them), so the brief-step test uses the synthetic
``ztest-category``/``ZTST`` surface that never collides with the loaded map (as in test_impact).
"""

from __future__ import annotations

import itertools
import json
from datetime import UTC, date, datetime

import pytest
from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.orm import Session

from seismo.collectors.base import RawEventDraft, Window
from seismo.config import settings
from seismo.hindcast.assertions import AssertionResult, evaluate
from seismo.hindcast.case import (
    Assertion,
    Case,
    load_case,
    load_case_by_name,
)
from seismo.hindcast.loaders import load_arxiv, load_github_readmes, load_hn
from seismo.hindcast.runner import run_hindcast

_UID = itertools.count(1)
CATEGORY = "ztest-category"
TICKER = "ZTST"


@pytest.fixture(autouse=True)
def _mock_provider(monkeypatch) -> None:  # type: ignore[no-untyped-def]
    """Force ``mock`` — the dev .env sets ollama, which would make the brief step hit a model."""
    monkeypatch.setattr(settings, "llm_provider", "mock")


# --- seeding helpers --------------------------------------------------------


def _entity(
    session: Session,
    *,
    anchors: dict[str, str],
    category: str | None = None,
    created: datetime,
) -> int:
    eid = int(
        session.execute(
            text(
                "INSERT INTO entities (entity_type, canonical_name, category, created_at, attrs) "
                "VALUES ('project', :n, :cat, :c, CAST(:a AS JSONB)) RETURNING id"
            ),
            {
                "n": f"ent{next(_UID)}",
                "cat": category,
                "c": created,
                "a": json.dumps({"anchors": anchors}),
            },
        ).scalar_one()
    )
    ev = int(
        session.execute(
            text(
                "INSERT INTO raw_events (source, source_event_uid, event_type, occurred_at, "
                "payload) VALUES ('github', :u, 'repo_discovered', :o, '{}') RETURNING id"
            ),
            {"u": f"t:{next(_UID)}", "o": created},
        ).scalar_one()
    )
    session.execute(
        text(
            "INSERT INTO entity_links (entity_id, raw_event_id, rule, confidence, "
            "evidence_occurred_at) VALUES (:e, :ev, 'attach', 1.0, :o)"
        ),
        {"e": eid, "ev": ev, "o": created},
    )
    if category is not None:
        session.execute(
            text(
                "INSERT INTO entity_category_history (entity_id, category, effective_at) "
                "VALUES (:e, :cat, :eff)"
            ),
            {"e": eid, "cat": category, "eff": created},
        )
    session.flush()
    return eid


def _momentum(session: Session, eid: int, day: date, state: str, p: float = 0.9) -> None:
    session.execute(
        text(
            "INSERT INTO momentum_states (entity_id, day, state, score, inputs) "
            "VALUES (:e, :d, :s, :p, CAST(:i AS JSONB)) "
            "ON CONFLICT (entity_id, day) DO UPDATE SET state = EXCLUDED.state"
        ),
        {"e": eid, "d": day, "s": state, "p": p, "i": json.dumps({"P": p})},
    )


def _gate(session: Session, eid: int, week: date, decision: str, reason: str | None = None) -> None:
    session.execute(
        text(
            "INSERT INTO gate_decisions (entity_id, week, decision, score, components) "
            "VALUES (:e, :w, :d, 0.5, CAST(:c AS JSONB))"
        ),
        {"e": eid, "w": week, "d": decision, "c": json.dumps({"reason": reason})},
    )


def _brief(session: Session, eid: int, brief: dict, status: str = "draft") -> None:
    session.execute(
        text(
            "INSERT INTO impact_briefs (entity_id, version, as_of, brief, status, model) "
            "VALUES (:e, 1, now(), CAST(:b AS JSONB), :s, 'mock')"
        ),
        {"e": eid, "b": json.dumps(brief), "s": status},
    )


def _card(session: Session, eid: int, as_of: datetime) -> None:
    session.execute(
        text(
            "INSERT INTO comprehension_cards (entity_id, version, as_of, card, model, status) "
            "VALUES (:e, 1, :as_of, CAST(:card AS JSONB), 'mock', 'ok')"
        ),
        {
            "e": eid,
            "as_of": as_of,
            "card": json.dumps(
                {"what_it_is": "a fast engine", "function": "serves", "confidence": "high"}
            ),
        },
    )


def _map_surface(session: Session) -> None:
    doc = {
        "ticker": TICKER,
        "name": f"{TICKER} Corp",
        "sector": "test",
        "revenue_lines": [
            {
                "id": "datacenter",
                "name": "Data Center",
                "share_of_revenue": 0.8,
                "source": "test",
                "threat_surface": [{"category": CATEGORY, "relation": "demand_risk", "core": True}],
            }
        ],
        "updated": "2026-07-01",
    }
    session.execute(
        text(
            "INSERT INTO exposure_companies (ticker, name, sector, doc, loaded_at) "
            "VALUES (:t, :n, 'test', CAST(:d AS JSONB), now()) "
            "ON CONFLICT (ticker) DO UPDATE SET doc = EXCLUDED.doc"
        ),
        {"t": TICKER, "n": doc["name"], "d": json.dumps(doc)},
    )
    session.execute(
        text(
            "INSERT INTO reach_links (category, ticker, revenue_line, relation, core) "
            "VALUES (:c, :t, 'datacenter', 'demand_risk', true) "
            "ON CONFLICT (category, ticker, revenue_line, relation) DO UPDATE SET core = true"
        ),
        {"c": CATEGORY, "t": TICKER},
    )
    session.flush()


def _assn(atype: str, **params: object) -> Assertion:
    return Assertion.model_validate({"id": "X", "type": atype, **params})


AS_OF = datetime(2024, 5, 31, 23, 59, 59, tzinfo=UTC)
BORN = datetime(2024, 1, 15, tzinfo=UTC)


def _eval(session: Session, a: Assertion, as_of: datetime = AS_OF) -> AssertionResult:
    dummy = Case.model_validate(
        {
            "case": "t",
            "window": {"from": "2024-01-01", "to": "2024-07-31"},
            "assertions": [{"id": "d", "type": "brief_absent", "entity": "github:none/none"}],
        }
    )
    return evaluate(session, dummy, a, default_as_of=as_of)


# --- case format ------------------------------------------------------------


def test_shipped_cases_load_and_validate() -> None:
    deepseek = load_case_by_name("deepseek")
    assert deepseek.name == "deepseek"
    assert deepseek.brief is not None and deepseek.brief.as_of == date(2024, 5, 31)
    assert {a.id for a in deepseek.assertions} == {"H1a", "H1b", "H2"}
    assert "deepseek-ai/DeepSeek-V2" in deepseek.seeds.github

    flop = load_case_by_name("reflection70b")
    assert flop.brief is None  # a flop has no brief target
    assert {a.type for a in flop.assertions} == {"momentum", "gate", "brief_absent"}


def test_unknown_assertion_type_is_rejected() -> None:
    with pytest.raises(ValidationError):
        Case.model_validate(
            {
                "case": "bad",
                "window": {"from": "2024-01-01", "to": "2024-02-01"},
                "assertions": [{"id": "H", "type": "telepathy"}],
            }
        )


def test_window_to_before_from_is_rejected() -> None:
    with pytest.raises(ValidationError):
        Case.model_validate(
            {
                "case": "bad",
                "window": {"from": "2024-02-01", "to": "2024-01-01"},
                "assertions": [{"id": "H", "type": "brief_absent", "entity": "github:a/b"}],
            }
        )


def test_missing_case_by_name(tmp_path) -> None:  # type: ignore[no-untyped-def]
    with pytest.raises(FileNotFoundError):
        load_case_by_name("nope", cases_dir=tmp_path)


def test_load_case_roundtrip(tmp_path) -> None:  # type: ignore[no-untyped-def]
    p = tmp_path / "c.yaml"
    p.write_text(
        "case: c\nwindow: {from: 2024-01-01, to: 2024-01-07}\n"
        "assertions:\n  - id: A\n    type: momentum\n    entity: github:a/b\n"
        "    states: [breakout]\n"
    )
    case = load_case(p)
    assert case.assertions[0].params["states"] == ["breakout"]


# --- identity evaluator -----------------------------------------------------


def test_identity_single_entity_passes(db_session: Session) -> None:
    _entity(
        db_session,
        anchors={"github": "deepseek-ai/deepseek-v2", "arxiv": "2405.04434"},
        created=BORN,
    )
    r = _eval(
        db_session, _assn("identity", refs=["github:deepseek-ai/deepseek-v2", "arxiv:2405.04434"])
    )
    assert r.passed, r.detail


def test_identity_distinct_entities_fail(db_session: Session) -> None:
    _entity(db_session, anchors={"github": "a/one"}, created=BORN)
    _entity(db_session, anchors={"arxiv": "1111.2222"}, created=BORN)
    r = _eval(db_session, _assn("identity", refs=["github:a/one", "arxiv:1111.2222"]))
    assert not r.passed and "distinct" in r.detail


def test_identity_unresolved_ref_fails(db_session: Session) -> None:
    r = _eval(db_session, _assn("identity", refs=["github:ghost/repo"]))
    assert not r.passed and "unresolved" in r.detail


# --- momentum evaluator -----------------------------------------------------


def test_momentum_reached_passes(db_session: Session) -> None:
    eid = _entity(db_session, anchors={"github": "a/rise"}, created=BORN)
    _momentum(db_session, eid, date(2024, 5, 20), "accelerating")
    r = _eval(
        db_session, _assn("momentum", entity="github:a/rise", states=["accelerating", "breakout"])
    )
    assert r.passed, r.detail


def test_momentum_not_reached_fails(db_session: Session) -> None:
    eid = _entity(db_session, anchors={"github": "a/flat"}, created=BORN)
    _momentum(db_session, eid, date(2024, 5, 20), "simmering")
    r = _eval(db_session, _assn("momentum", entity="github:a/flat", states=["breakout"]))
    assert not r.passed and "never reached" in r.detail


def test_momentum_never_passes_when_below_ceiling(db_session: Session) -> None:
    # mode=never: a flop that peaks at simmering must PASS "never reached accelerating/breakout".
    eid = _entity(db_session, anchors={"hf": "org/flop"}, created=BORN)
    _momentum(db_session, eid, date(2024, 5, 10), "simmering")
    r = _eval(
        db_session,
        _assn("momentum", entity="hf:org/flop", mode="never", states=["accelerating", "breakout"]),
    )
    assert r.passed and "never reached" in r.detail


def test_momentum_never_fails_when_ceiling_breached(db_session: Session) -> None:
    # mode=never must FAIL if the entity did reach a forbidden state.
    eid = _entity(db_session, anchors={"hf": "org/hot"}, created=BORN)
    _momentum(db_session, eid, date(2024, 5, 10), "accelerating")
    r = _eval(
        db_session,
        _assn("momentum", entity="hf:org/hot", mode="never", states=["accelerating", "breakout"]),
    )
    assert not r.passed and "forbidden" in r.detail


def test_momentum_never_fails_without_history(db_session: Session) -> None:
    # mode=never can't pass vacuously: an entity with no momentum rows is not gradable.
    eid = _entity(db_session, anchors={"hf": "org/empty"}, created=BORN)
    assert eid  # resolves, but has no momentum_states rows
    r = _eval(
        db_session,
        _assn("momentum", entity="hf:org/empty", mode="never", states=["breakout"]),
    )
    assert not r.passed and "no momentum rows" in r.detail


def test_momentum_respects_as_of_bound(db_session: Session) -> None:
    # a breakout AFTER the as-of bound must not count (as-of purity)
    eid = _entity(db_session, anchors={"github": "a/late"}, created=BORN)
    _momentum(db_session, eid, date(2024, 7, 1), "breakout")
    r = _eval(
        db_session,
        _assn("momentum", entity="github:a/late", states=["breakout"], as_of=date(2024, 5, 31)),
    )
    assert not r.passed


# --- gate evaluator ---------------------------------------------------------


def test_gate_never_candidate_counts_as_suppressed(db_session: Session) -> None:
    _entity(db_session, anchors={"github": "a/quiet"}, created=BORN)
    r = _eval(db_session, _assn("gate", entity="github:a/quiet", decision="suppressed"))
    assert r.passed and "never a gate candidate" in r.detail


def test_gate_suppressed_row_passes(db_session: Session) -> None:
    eid = _entity(db_session, anchors={"github": "a/flop"}, created=BORN)
    _gate(db_session, eid, date(2024, 5, 27), "suppressed", reason="unmapped_reach")
    r = _eval(
        db_session,
        _assn("gate", entity="github:a/flop", decision="suppressed", reason="unmapped_reach"),
    )
    assert r.passed, r.detail


def test_gate_passed_when_suppression_expected_fails(db_session: Session) -> None:
    eid = _entity(db_session, anchors={"github": "a/pass"}, created=BORN)
    _gate(db_session, eid, date(2024, 5, 27), "pass")
    r = _eval(db_session, _assn("gate", entity="github:a/pass", decision="suppressed"))
    assert not r.passed and "PASSED" in r.detail


def test_gate_pass_expected_passes(db_session: Session) -> None:
    eid = _entity(db_session, anchors={"github": "a/win"}, created=BORN)
    _gate(db_session, eid, date(2024, 5, 27), "pass")
    r = _eval(db_session, _assn("gate", entity="github:a/win", decision="pass"))
    assert r.passed, r.detail


# --- brief_absent evaluator -------------------------------------------------


def test_brief_absent_passes_when_none(db_session: Session) -> None:
    _entity(db_session, anchors={"github": "a/nobrief"}, created=BORN)
    r = _eval(db_session, _assn("brief_absent", entity="github:a/nobrief"))
    assert r.passed, r.detail


def test_brief_absent_fails_when_present(db_session: Session) -> None:
    eid = _entity(db_session, anchors={"github": "a/hasbrief"}, created=BORN)
    _brief(db_session, eid, {"summary": "x"})
    r = _eval(db_session, _assn("brief_absent", entity="github:a/hasbrief"))
    assert not r.passed and "flop must be brief-free" in r.detail


# --- brief evaluator (H2 schema facts) --------------------------------------


def _deepseek_brief() -> dict:
    return {
        "entity_ref": "deepseek-v2",
        "mechanisms": ["cost_collapse", "commoditization"],
        "transmission_path": [
            {"from_node": "deepseek", "to_node": "gpu demand", "effect": "falls"}
        ],
        "exposures": [
            {
                "kind": "ticker",
                "ref": "NVDA",
                "revenue_line": "datacenter",
                "direction": "negative",
                "magnitude_class": "material",
            },
            {
                "kind": "ticker",
                "ref": "MSFT",
                "revenue_line": "azure",
                "direction": "positive",
                "magnitude_class": "marginal",
            },
        ],
        "counter_mechanism": "Jevons paradox: cheaper inference grows total token volume.",
        "observables": [
            {
                "statement": "tokens per customer",
                "source": "system",
                "system_metric": "hf_downloads_30d",
                "horizon": "quarters",
                "direction_if_thesis_holds": "up",
            }
        ],
        "confidence": "med",
        "horizon": "1-2y",
        "summary": "cost collapse",
        "evidence_refs": [1],
    }


def test_brief_facts_all_pass(db_session: Session) -> None:
    eid = _entity(db_session, anchors={"github": "deepseek-ai/deepseek-v2"}, created=BORN)
    _brief(db_session, eid, _deepseek_brief())
    r = _eval(
        db_session,
        _assn(
            "brief",
            entity="github:deepseek-ai/deepseek-v2",
            mechanisms_superset=["cost_collapse"],
            mechanisms_intersect=["commoditization"],
            exposures_include_tickers=["NVDA"],
            exposures_include_any_ticker=["MSFT", "GOOGL"],
            counter_mechanism_nonempty=True,
            observables_nonempty=True,
            observables_have_horizon=True,
        ),
    )
    assert r.passed, r.detail


def test_brief_missing_mechanism_fails(db_session: Session) -> None:
    eid = _entity(db_session, anchors={"github": "d/v"}, created=BORN)
    brief = _deepseek_brief() | {"mechanisms": ["commoditization"]}  # no cost_collapse
    _brief(db_session, eid, brief)
    r = _eval(
        db_session, _assn("brief", entity="github:d/v", mechanisms_superset=["cost_collapse"])
    )
    assert not r.passed and "cost_collapse" in r.detail


def test_brief_missing_ticker_fails(db_session: Session) -> None:
    eid = _entity(db_session, anchors={"github": "d/v2"}, created=BORN)
    brief = _deepseek_brief()
    brief["exposures"] = [brief["exposures"][1]]  # MSFT only, no NVDA
    _brief(db_session, eid, brief)
    r = _eval(db_session, _assn("brief", entity="github:d/v2", exposures_include_tickers=["NVDA"]))
    assert not r.passed and "NVDA" in r.detail


# --- end-to-end runner: negative shape (green, deterministic) ---------------


def _synthetic_github_loader(session: Session, case: Case, warnings: list[str]) -> None:
    """Inject a thin GitHub trail so the real pipeline creates the entity — no network."""
    for repo in case.seeds.github:
        session.execute(
            text(
                "INSERT INTO raw_events (source, source_event_uid, event_type, occurred_at, "
                "origin, payload) VALUES ('github', :u, 'repo_discovered', :o, 'backfill', "
                "CAST(:p AS JSONB))"
            ),
            {
                "u": f"repo_discovered:{repo}",
                "o": datetime(2024, 9, 1, 12, tzinfo=UTC),
                "p": json.dumps({"repo": repo, "backfilled": True}),
            },
        )
    warnings.append(f"synthetic loader seeded {case.seeds.github}")
    session.flush()


def test_runner_negative_case_is_green(clean_db: Session) -> None:
    case = Case.model_validate(
        {
            "case": "synthflop",
            "window": {"from": "2024-09-01", "to": "2024-09-03"},
            "seeds": {"github": ["synth/flop"]},
            "assertions": [
                {
                    "id": "G",
                    "type": "gate",
                    "entity": "github:synth/flop",
                    "decision": "suppressed",
                },
                {"id": "B", "type": "brief_absent", "entity": "github:synth/flop"},
            ],
        }
    )
    result = run_hindcast(
        clean_db, case, reload=True, loader=_synthetic_github_loader, comprehend=False
    )
    assert result.passed, [r.detail for r in result.results if not r.passed]
    assert result.run_id is not None
    assert "Hindcast — synthflop — PASS" in result.report
    # the replay actually ran the pipeline — the entity now exists
    row = clean_db.execute(
        text("SELECT COUNT(*) FROM hindcast_runs WHERE case_name = 'synthflop'")
    ).scalar_one()
    assert row == 1


# --- end-to-end runner: the forced-brief step -------------------------------


def test_runner_brief_step_drafts_and_asserts(clean_db: Session) -> None:
    _map_surface(clean_db)
    eid = _entity(
        clean_db,
        anchors={"github": "pos/repo"},
        category=CATEGORY,
        created=datetime(2024, 5, 1, tzinfo=UTC),
    )
    _card(clean_db, eid, datetime(2024, 5, 1, tzinfo=UTC))
    case = Case.model_validate(
        {
            "case": "synthpos",
            "window": {"from": "2024-05-30", "to": "2024-05-31"},
            "brief": {"as_of": "2024-05-31", "entity": "github:pos/repo"},
            "assertions": [
                {
                    "id": "H2",
                    "type": "brief",
                    "entity": "github:pos/repo",
                    "as_of": "2024-05-31",
                    "counter_mechanism_nonempty": True,
                    "observables_nonempty": True,
                    "observables_have_horizon": True,
                },
            ],
        }
    )
    result = run_hindcast(clean_db, case, reload=False, comprehend=False)
    assert result.passed, [r.detail for r in result.results if not r.passed]
    # a draft brief was actually written by the forced brief step (mock provider)
    n = clean_db.execute(
        text("SELECT COUNT(*) FROM impact_briefs WHERE entity_id = :e AND status = 'draft'"),
        {"e": eid},
    ).scalar_one()
    assert n == 1


# --- case-scoped historical loaders (HN / arXiv) ----------------------------


class _FakeHN:
    """Stands in for HackerNewsCollector — records the window it was asked for."""

    def __init__(self) -> None:
        self.window: Window | None = None

    def discover(self, window: Window) -> list[RawEventDraft]:
        self.window = window
        return [
            RawEventDraft(
                source="hn",
                source_event_uid="story-1",
                event_type="story",
                occurred_at=datetime(2024, 9, 15, tzinfo=UTC),
                payload={"points": 400, "title": "Reflection 70B is the best open model"},
            )
        ]

    def track(self, targets: list[object], window: Window) -> list[RawEventDraft]:
        return []


class _FakeArxiv:
    def __init__(self) -> None:
        self.ids: list[str] | None = None

    def fetch_ids(self, arxiv_ids: list[str]) -> list[RawEventDraft]:
        self.ids = arxiv_ids
        return [
            RawEventDraft(
                source="arxiv",
                source_event_uid=aid,
                event_type="paper_published",
                occurred_at=datetime(2024, 5, 6, tzinfo=UTC),
                payload={"arxiv_id": aid},
            )
            for aid in arxiv_ids
        ]


class _FakeGitHubReadme:
    """Records which repos were asked for; returns a now-dated README draft per target (like the
    real collector, whose enrichment events are ``occurred_at=now()``)."""

    def __init__(self) -> None:
        self.asked: list[str] = []

    def readmes(self, targets: list[object], window: Window) -> list[RawEventDraft]:
        self.asked = [t.native_id for t in targets]  # type: ignore[attr-defined]
        return [
            RawEventDraft(
                source="github",
                source_event_uid=f"repo_readme:{t.native_id}",  # type: ignore[attr-defined]
                event_type="repo_readme",
                occurred_at=datetime(2026, 7, 11, tzinfo=UTC),  # "now" — must be backdated
                payload={"full_name": t.native_id, "text": "cites arxiv:0000.00002"},  # type: ignore[attr-defined]
            )
            for t in targets
        ]


def test_load_github_readmes_filters_orgs_and_backdates(db_session: Session) -> None:
    fake = _FakeGitHubReadme()
    win = Window(since=datetime(2024, 1, 1, tzinfo=UTC), until=datetime(2024, 7, 31, tzinfo=UTC))
    # a bare org handle has no README — only owner/repo seeds are fetched
    n = load_github_readmes(
        db_session, ["zz-testorg/zz-testrepo", "zz-testorg"], win, collector=fake
    )
    db_session.flush()
    assert n == 1 and fake.asked == ["zz-testorg/zz-testrepo"]
    row = db_session.execute(
        text(
            "SELECT origin, occurred_at FROM raw_events WHERE source = 'github' "
            "AND source_event_uid = 'repo_readme:zz-testorg/zz-testrepo'"
        )
    ).first()
    assert row is not None
    assert row[0] == "backfill"
    # backdated to window.since so the R1 merge it justifies is visible at a past hindcast as-of
    assert row[1] == win.since


def test_load_github_readmes_no_repo_seeds_is_noop(db_session: Session) -> None:
    win = Window(since=datetime(2024, 1, 1, tzinfo=UTC), until=datetime(2024, 7, 31, tzinfo=UTC))
    assert load_github_readmes(db_session, ["just-an-org"], win, collector=_FakeGitHubReadme()) == 0


def test_load_hn_points_collector_at_window_and_marks_backfill(db_session: Session) -> None:
    fake = _FakeHN()
    win = Window(since=datetime(2024, 9, 1, tzinfo=UTC), until=datetime(2024, 9, 30, tzinfo=UTC))
    n = load_hn(db_session, win, collector=fake)
    db_session.flush()
    assert n == 1 and fake.window == win  # the loader passed the case window through
    origin = db_session.execute(
        text("SELECT origin FROM raw_events WHERE source = 'hn' AND source_event_uid = 'story-1'")
    ).scalar_one()
    assert origin == "backfill"  # scope-wipeable on --reload


def test_load_arxiv_fetches_seed_ids_and_marks_backfill(db_session: Session) -> None:
    # A synthetic id — db_session is the shared dev DB, and the real 2405.04434 already lives there
    # (persist would skip the dupe), so we use an id that never collides.
    fake = _FakeArxiv()
    n = load_arxiv(db_session, ["0000.00001"], collector=fake)
    db_session.flush()
    assert n == 1 and fake.ids == ["0000.00001"]
    row = db_session.execute(
        text(
            "SELECT origin, event_type FROM raw_events WHERE source = 'arxiv' "
            "AND source_event_uid = '0000.00001'"
        )
    ).first()
    assert row is not None and row[0] == "backfill" and row[1] == "paper_published"


def test_load_arxiv_empty_is_a_noop(db_session: Session) -> None:
    assert load_arxiv(db_session, [], collector=_FakeArxiv()) == 0


def test_loaders_are_idempotent(db_session: Session) -> None:
    win = Window(since=datetime(2024, 9, 1, tzinfo=UTC), until=datetime(2024, 9, 30, tzinfo=UTC))
    assert load_hn(db_session, win, collector=_FakeHN()) == 1
    db_session.flush()
    assert load_hn(db_session, win, collector=_FakeHN()) == 0  # same natural key → no dupe
