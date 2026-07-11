"""Stage 7 — Impact brief (doc 08). The contract + its post-validation, the deterministic input
pack (map-slice selection, as-of correctness), the mock end-to-end path (fallback → draft →
versioned
store), the budget-ceiling → ``pending`` rail, and candidate selection from the gate's passed queue.

Runs on ``clean_db`` with the default ``mock`` provider ($0). ``exposure_companies``/``reach_links``
are not cleared by ``clean_db`` (the map is global), so tests use a synthetic ticker/category that
never collides with the loaded 8-company slice; every write is inside the rolled-back transaction.
"""

from __future__ import annotations

import itertools
import json
from datetime import UTC, date, datetime, timedelta

import pytest
from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.orm import Session

from seismo.checkpoints import impact
from seismo.checkpoints.contracts import ImpactBrief, brief_tool_schema
from seismo.checkpoints.impact_pack import build_brief_pack
from seismo.config import settings

_UID = itertools.count(1)
# A synthetic category + ticker that never collide with the loaded 8-company map (clean_db does not
# clear reach_links/exposure_companies — the map is global — so a real slug would leak real edges).
CATEGORY = "ztest-category"
TICKER = "ZTST"


# --- fixtures / helpers -----------------------------------------------------


@pytest.fixture(autouse=True)
def _mock_provider(monkeypatch) -> None:
    """Force the ``mock`` provider so the end-to-end path is deterministic + $0. The dev ``.env``
    sets ``ollama`` and the app may be running, which would make these tests hit a real model."""
    monkeypatch.setattr(settings, "llm_provider", "mock")


def _company(session: Session, ticker: str, lines: list[dict]) -> None:
    doc = {
        "ticker": ticker,
        "name": f"{ticker} Corp",
        "sector": "test",
        "revenue_lines": lines,
        "moat_notes": "a moat",
        "sensitivity_notes": "watch this",
        "updated": "2026-07-01",
    }
    session.execute(
        text(
            "INSERT INTO exposure_companies (ticker, name, sector, doc, loaded_at) "
            "VALUES (:t, :n, :s, CAST(:d AS JSONB), now()) "
            "ON CONFLICT (ticker) DO UPDATE SET doc = EXCLUDED.doc"
        ),
        {"t": ticker, "n": doc["name"], "s": doc["sector"], "d": json.dumps(doc)},
    )


def _reach(
    session: Session, category: str, ticker: str, line: str, relation: str, core: bool
) -> None:
    session.execute(
        text(
            "INSERT INTO reach_links (category, ticker, revenue_line, relation, core) "
            "VALUES (:c, :t, :l, :r, :core) "
            "ON CONFLICT (category, ticker, revenue_line, relation) "
            "DO UPDATE SET core = EXCLUDED.core"
        ),
        {"c": category, "t": ticker, "l": line, "r": relation, "core": core},
    )


def _map_surface(session: Session, category: str = CATEGORY, relation: str = "demand_risk") -> None:
    """A one-company map surface touching ``category`` — a datacenter line via ``relation``."""
    _company(
        session,
        TICKER,
        [
            {
                "id": "datacenter",
                "name": "Data Center",
                "share_of_revenue": 0.8,
                "source": "test",
                "threat_surface": [{"category": category, "relation": relation, "core": True}],
            }
        ],
    )
    _reach(session, category, TICKER, "datacenter", relation, True)


def _entity(
    session: Session,
    *,
    category: str | None = CATEGORY,
    created: datetime,
    card_status: str = "ok",
    state: str = "breakout",
) -> int:
    eid = int(
        session.execute(
            text(
                "INSERT INTO entities (entity_type, canonical_name, created_at, attrs) "
                "VALUES ('project', :n, :c, '{}') RETURNING id"
            ),
            {"n": f"ent{next(_UID)}", "c": created},
        ).scalar_one()
    )
    if category is not None:
        session.execute(
            text(
                "INSERT INTO entity_category_history (entity_id, category, effective_at) "
                "VALUES (:e, :cat, :eff)"
            ),
            {"e": eid, "cat": category, "eff": created},
        )
    ev = int(
        session.execute(
            text(
                "INSERT INTO raw_events (source, source_event_uid, event_type, occurred_at,"
                " payload) VALUES ('github', :u, 'repo_discovered', :o, '{}') RETURNING id"
            ),
            {"u": f"t:{next(_UID)}", "o": created},
        ).scalar_one()
    )
    session.execute(
        text(
            "INSERT INTO entity_links (entity_id, raw_event_id, rule, confidence,"
            " evidence_occurred_at) VALUES (:e, :ev, 'attach', 1.0, :o)"
        ),
        {"e": eid, "ev": ev, "o": created},
    )
    session.execute(
        text(
            "INSERT INTO momentum_states (entity_id, day, state, score, inputs) "
            "VALUES (:e, :d, :s, 0.9, CAST(:i AS JSONB))"
        ),
        {"e": eid, "d": created.date(), "s": state, "i": json.dumps({"P": 0.9})},
    )
    if card_status is not None:
        session.execute(
            text(
                "INSERT INTO comprehension_cards (entity_id, version, as_of, card, model, status) "
                "VALUES (:e, 1, :as_of, CAST(:card AS JSONB), 'mock', :st)"
            ),
            {
                "e": eid,
                "as_of": created,
                "card": json.dumps(
                    {"what_it_is": "a fast engine", "function": "serves", "confidence": "high"}
                ),
                "st": card_status,
            },
        )
    session.flush()
    return eid


# --- contract ---------------------------------------------------------------


def _valid_brief() -> dict:
    return {
        "entity_ref": "vllm",
        "mechanisms": ["substitution"],
        "transmission_path": [
            {"from_node": "vllm", "to_node": "inference cost", "effect": "falls"}
        ],
        "exposures": [
            {
                "kind": "ticker",
                "ref": TICKER,
                "revenue_line": "datacenter",
                "direction": "negative",
                "magnitude_class": "material",
            }
        ],
        "counter_mechanism": "Jevons: cheaper inference grows total volume.",
        "observables": [
            {
                "statement": "tokens per customer",
                "source": "system",
                "system_metric": "hf_downloads_30d",
                "horizon": "quarters",
                "direction_if_thesis_holds": "down",
            }
        ],
        "confidence": "med",
        "horizon": "1-2y",
        "summary": "a thesis",
        "evidence_refs": [1, 2],
    }


def test_contract_accepts_valid_and_rejects_bad_mechanism() -> None:
    assert ImpactBrief.model_validate(_valid_brief()).mechanisms == ["substitution"]
    bad = _valid_brief() | {"mechanisms": ["telepathy"]}
    with pytest.raises(ValidationError):
        ImpactBrief.model_validate(bad)


def test_contract_requires_counter_and_observable() -> None:
    with pytest.raises(ValidationError):
        ImpactBrief.model_validate(_valid_brief() | {"counter_mechanism": ""})
    with pytest.raises(ValidationError):
        ImpactBrief.model_validate(_valid_brief() | {"observables": []})


def test_contract_truncates_summary_to_200_words() -> None:
    long = _valid_brief() | {"summary": " ".join(["w"] * 300)}
    assert len(ImpactBrief.model_validate(long).summary.split()) == 200


def test_tool_schema_carries_mechanism_enum() -> None:
    schema = brief_tool_schema()
    assert "cost_collapse" in schema["properties"]["mechanisms"]["items"]["enum"]
    assert schema["additionalProperties"] is False


# --- input pack -------------------------------------------------------------


def test_pack_is_deterministic_asof_and_map_scoped(clean_db: Session) -> None:
    session = clean_db
    _map_surface(session)
    # a second, UNRELATED company on a different category must NOT leak into the pack.
    _company(
        session,
        "ZOTH",
        [
            {
                "id": "ads",
                "name": "Ads",
                "share_of_revenue": 0.5,
                "source": "x",
                "threat_surface": [{"category": "ad-tech", "relation": "demand_risk"}],
            }
        ],
    )
    _reach(session, "ad-tech", "ZOTH", "ads", "demand_risk", False)

    t0 = datetime(2024, 1, 1, tzinfo=UTC)
    eid = _entity(session, created=t0)
    as_of = t0 + timedelta(days=10)

    pack = build_brief_pack(session, eid, as_of)
    again = build_brief_pack(session, eid, as_of)
    assert pack.markdown == again.markdown
    assert pack.category == CATEGORY
    assert TICKER in pack.markdown and "Mechanism taxonomy" in pack.markdown
    assert "a fast engine" in pack.markdown  # the comprehension card is folded in
    assert "ZOTH" not in pack.markdown, "only the matched category's map surface is in the pack"
    # demand_risk permits substitution/cost_collapse/commoditization (exposure.RELATION_MECHANISMS)
    assert pack.reach.allowed_mechanisms == {"substitution", "cost_collapse", "commoditization"}
    assert pack.reach.valid_lines[TICKER] == {"datacenter"}


# --- post-validation (doc 08 §2) --------------------------------------------


def test_post_validation_rejects_unknown_revenue_line(clean_db: Session) -> None:
    session = clean_db
    _map_surface(session)
    t0 = datetime(2024, 1, 1, tzinfo=UTC)
    pack = build_brief_pack(session, _entity(session, created=t0), t0 + timedelta(days=1))
    bad = ImpactBrief.model_validate(
        _valid_brief()
        | {
            "exposures": [
                {
                    "kind": "ticker",
                    "ref": TICKER,
                    "revenue_line": "made-up-line",
                    "direction": "negative",
                    "magnitude_class": "material",
                }
            ]
        }
    )
    assert impact._post_validate(bad, pack) is not None


def test_post_validation_rejects_illegal_mechanism(clean_db: Session) -> None:
    session = clean_db
    _map_surface(session)  # relation demand_risk → enablement is NOT legal
    t0 = datetime(2024, 1, 1, tzinfo=UTC)
    pack = build_brief_pack(session, _entity(session, created=t0), t0 + timedelta(days=1))
    bad = ImpactBrief.model_validate(_valid_brief() | {"mechanisms": ["enablement"]})
    assert impact._post_validate(bad, pack) is not None
    ok = ImpactBrief.model_validate(_valid_brief() | {"mechanisms": ["cost_collapse"]})
    assert impact._post_validate(ok, pack) is None


def test_post_validation_rejects_keyword_counter_mechanism(clean_db: Session) -> None:
    # A capable model sometimes fills counter_mechanism with a bare taxonomy word instead of an
    # argument (observed with qwen 7B). idea-spec §7: a one-sided brief is marketing — reject it.
    session = clean_db
    _map_surface(session)
    t0 = datetime(2024, 1, 1, tzinfo=UTC)
    pack = build_brief_pack(session, _entity(session, created=t0), t0 + timedelta(days=1))
    keyword = ImpactBrief.model_validate(_valid_brief() | {"counter_mechanism": "dependency_risk"})
    assert impact._post_validate(keyword, pack) is not None
    terse = ImpactBrief.model_validate(_valid_brief() | {"counter_mechanism": "won't matter"})
    assert impact._post_validate(terse, pack) is not None
    real = ImpactBrief.model_validate(
        _valid_brief()
        | {"counter_mechanism": "Jevons: cheaper inference expands total agent usage."}
    )
    assert impact._post_validate(real, pack) is None


# --- mock end-to-end + versioning -------------------------------------------


def test_mock_brief_stores_valid_versioned_draft(clean_db: Session) -> None:
    session = clean_db
    _map_surface(session)
    t0 = datetime(2024, 1, 1, tzinfo=UTC)
    eid = _entity(session, created=t0)

    stats = impact.run_brief(session, t0 + timedelta(days=1), entity_id=eid)
    assert stats.drafted == 1 and stats.failed == 0
    row = (
        session.execute(
            text("SELECT version, status, brief FROM impact_briefs WHERE entity_id = :e"),
            {"e": eid},
        )
        .mappings()
        .one()
    )
    assert row["version"] == 1 and row["status"] == "draft"
    ImpactBrief.model_validate(row["brief"])  # the stored fallback brief is schema-valid

    # A forced second run appends version 2 (old retained).
    impact.run_brief(session, t0 + timedelta(days=2), entity_id=eid)
    versions = (
        session.execute(
            text("SELECT version FROM impact_briefs WHERE entity_id = :e ORDER BY version"),
            {"e": eid},
        )
        .scalars()
        .all()
    )
    assert versions == [1, 2]


def test_budget_ceiling_marks_pending_without_calling(clean_db: Session, monkeypatch) -> None:
    session = clean_db
    _map_surface(session)
    t0 = datetime(2024, 1, 1, tzinfo=UTC)
    eid = _entity(session, created=t0)

    monkeypatch.setattr(settings, "llm_provider", "anthropic")
    monkeypatch.setattr(settings, "llm_budget_usd", 0.0)
    # If the budget gate failed, this would try the network and raise.
    stats = impact.run_brief(session, t0 + timedelta(days=1), entity_id=eid)
    assert stats.pending == 1 and stats.drafted == 0
    status = session.execute(
        text("SELECT status FROM impact_briefs WHERE entity_id = :e"), {"e": eid}
    ).scalar_one()
    assert status == "pending"


# --- candidate selection from the gate's passed queue -----------------------


def test_queue_mode_briefs_passed_and_skips_existing(clean_db: Session) -> None:
    session = clean_db
    _map_surface(session)
    t0 = datetime(2024, 1, 1, tzinfo=UTC)
    week = date(2024, 1, 1)  # a Monday
    passed = _entity(session, created=t0)
    suppressed = _entity(session, created=t0)
    session.execute(
        text(
            "INSERT INTO gate_decisions (entity_id, week, decision, score, components) VALUES "
            "(:p, :w, 'pass', 0.9, '{}'), (:s, :w, 'suppressed', 0.1, '{}')"
        ),
        {"p": passed, "s": suppressed, "w": week},
    )
    session.flush()

    stats = impact.run_brief(session, impact.week_as_of(week), week_start=week)
    assert stats.candidates == 1 and stats.drafted == 1
    # only the passed entity got a brief
    briefed = session.execute(text("SELECT entity_id FROM impact_briefs")).scalars().all()
    assert briefed == [passed]

    # A second queue run is idempotent — the existing draft is skipped, not re-drafted.
    again = impact.run_brief(session, impact.week_as_of(week), week_start=week)
    assert again.drafted == 0 and again.skipped == 1
