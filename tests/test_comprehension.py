"""Stage 4 — Comprehension (doc 05). Contract validation, the pure evidence-pack builder, the
trigger policy, and the mock end-to-end path (card generation → validation → versioned storage),
plus the two safety rails: category-disagreement flagging and the budget-ceiling → ``pending`` gate.

Runs on ``clean_db`` with the default ``mock`` provider ($0, no network). The one budget test flips
the provider to ``anthropic`` but sets the budget to 0 so the call is never attempted.
"""

from __future__ import annotations

import itertools
from datetime import UTC, datetime, timedelta

import pytest
from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.orm import Session

from seismo.checkpoints import comprehend as comp
from seismo.checkpoints.contracts import ComprehensionCard, card_tool_schema
from seismo.checkpoints.evidence import build_evidence_pack
from seismo.config import settings

_UID = itertools.count(1)


# --- helpers ----------------------------------------------------------------


def _json(value: dict) -> str:
    import json

    return json.dumps(value)


def _entity(
    session: Session,
    name: str,
    *,
    etype: str = "project",
    created: datetime,
    category: str | None = None,
    attrs: dict | None = None,
) -> int:
    eid = int(
        session.execute(
            text(
                """
                INSERT INTO entities (entity_type, canonical_name, created_at, attrs)
                VALUES (:t, :n, :c, CAST(:a AS JSONB)) RETURNING id
                """
            ),
            {"t": etype, "n": name, "c": created, "a": _json(attrs or {})},
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
    return eid


def _event(
    session: Session,
    entity_id: int,
    *,
    source: str,
    event_type: str,
    occurred: datetime,
    payload: dict | None = None,
) -> int:
    uid = f"test:{next(_UID)}"
    ev = int(
        session.execute(
            text(
                """
                INSERT INTO raw_events (source, source_event_uid, event_type, occurred_at, payload)
                VALUES (:s, :u, :et, :o, CAST(:p AS JSONB)) RETURNING id
                """
            ),
            {"s": source, "u": uid, "et": event_type, "o": occurred, "p": _json(payload or {})},
        ).scalar_one()
    )
    session.execute(
        text(
            "INSERT INTO entity_links"
            " (entity_id, raw_event_id, rule, confidence, evidence_occurred_at)"
            " VALUES (:e, :ev, 'attach', 1.0, :o)"
        ),
        {"e": entity_id, "ev": ev, "o": occurred},
    )
    return ev


def _metric(session: Session, entity_id: int, metric: str, day: datetime, value: float) -> None:
    session.execute(
        text(
            "INSERT INTO entity_metrics_daily (entity_id, metric, day, value) "
            "VALUES (:e, :m, :d, :v)"
        ),
        {"e": entity_id, "m": metric, "d": day.date(), "v": value},
    )


# --- contract ---------------------------------------------------------------


def _valid_card_dict() -> dict:
    return {
        "entity_ref": "vllm",
        "what_it_is": "An inference server.",
        "category": "inference-runtime",
        "function": "Serves LLMs.",
        "claimed_advantage": "Fast.",
        "replaces_or_enables": ["hf-tgi"],
        "maturity_stage": "distribution",
        "who_is_behind": "vLLM team",
        "open_questions": [],
        "evidence_refs": [1, 2],
        "confidence": "high",
    }


def test_contract_accepts_valid_and_rejects_bad_vocab() -> None:
    assert ComprehensionCard.model_validate(_valid_card_dict()).category == "inference-runtime"
    bad_cat = _valid_card_dict() | {"category": "not-a-real-category"}
    with pytest.raises(ValidationError):
        ComprehensionCard.model_validate(bad_cat)
    bad_stage = _valid_card_dict() | {"maturity_stage": "world-domination"}
    with pytest.raises(ValidationError):
        ComprehensionCard.model_validate(bad_stage)


def test_contract_truncates_what_it_is_to_60_words() -> None:
    long = _valid_card_dict() | {"what_it_is": " ".join(["word"] * 100)}
    card = ComprehensionCard.model_validate(long)
    assert len(card.what_it_is.split()) == 60


def test_tool_schema_carries_vocab_enums() -> None:
    schema = card_tool_schema()
    assert "inference-runtime" in schema["properties"]["category"]["enum"]
    assert "distribution" in schema["properties"]["maturity_stage"]["enum"]
    assert schema["additionalProperties"] is False


# --- evidence pack ----------------------------------------------------------


def test_evidence_pack_is_bounded_deterministic_and_asof_correct(clean_db: Session) -> None:
    session = clean_db
    t0 = datetime(2024, 1, 1, tzinfo=UTC)
    eid = _entity(
        session,
        "proj",
        created=t0,
        category="inference-runtime",
        attrs={
            "text": "A fast serving engine.",
            "owner": "acme",
            "anchors": {"github": "acme/proj"},
        },
    )
    seen = _event(
        session,
        eid,
        source="hn",
        event_type="story",
        occurred=t0,
        payload={"title": "Show HN: proj", "points": 200},
    )
    # a future event must not appear in a pack built at t0.
    _event(
        session,
        eid,
        source="github",
        event_type="repo_snapshot",
        occurred=t0 + timedelta(days=10),
        payload={"stars": 999},
    )
    _metric(session, eid, "gh_stars", t0, 42)
    session.flush()

    as_of = t0 + timedelta(days=1)
    pack = build_evidence_pack(session, eid, as_of)
    again = build_evidence_pack(session, eid, as_of)
    assert pack.markdown == again.markdown, "pack builder must be deterministic"
    assert pack.rule_category == "inference-runtime"
    assert "acme/proj" in pack.markdown and "A fast serving engine." in pack.markdown
    assert seen in pack.event_ids
    assert "999" not in pack.markdown, "a future snapshot must be invisible at as_of"
    assert len(pack.markdown) <= 48000


# --- trigger policy ---------------------------------------------------------


def test_trigger_selects_new_survived_entity_with_breadth(clean_db: Session) -> None:
    session = clean_db
    t0 = datetime(2024, 1, 1, tzinfo=UTC)
    as_of = t0 + timedelta(days=30)
    good = _entity(session, "good", created=t0)  # 30d old
    _metric(session, good, "evidence_breadth", as_of, 2)
    young = _entity(session, "young", created=as_of - timedelta(days=3))  # < 7d
    _metric(session, young, "evidence_breadth", as_of, 3)
    thin = _entity(session, "thin", created=t0)  # breadth 1
    _metric(session, thin, "evidence_breadth", as_of, 1)
    session.flush()

    picked = comp.select_candidates(session, as_of)
    assert good in picked
    assert young not in picked and thin not in picked


def test_trigger_refreshes_on_promotion_since_last_card(clean_db: Session) -> None:
    session = clean_db
    t0 = datetime(2024, 1, 1, tzinfo=UTC)
    eid = _entity(session, "e", created=t0)
    # existing card as of day 10; a promotion lands day 20 -> should re-card.
    session.execute(
        text(
            "INSERT INTO comprehension_cards (entity_id, version, as_of, card, model, status) "
            "VALUES (:e, 1, :as_of, '{}', 'mock', 'ok')"
        ),
        {"e": eid, "as_of": t0 + timedelta(days=10)},
    )
    session.execute(
        text(
            "INSERT INTO maturity_promotions (entity_id, stage, promoted_at) "
            "VALUES (:e, 'usable_artifact', :t)"
        ),
        {"e": eid, "t": t0 + timedelta(days=20)},
    )
    session.flush()
    assert eid in comp.select_candidates(session, t0 + timedelta(days=25))


# --- mock end-to-end + versioning + category flag ---------------------------


def test_mock_comprehend_stores_valid_versioned_card(clean_db: Session) -> None:
    session = clean_db
    t0 = datetime(2024, 1, 1, tzinfo=UTC)
    eid = _entity(
        session, "proj", created=t0, category="inference-runtime", attrs={"text": "serving engine"}
    )
    _event(
        session,
        eid,
        source="arxiv",
        event_type="paper_published",
        occurred=t0,
        payload={"title": "a paper"},
    )
    session.flush()

    stats = comp.run_comprehend(session, t0 + timedelta(days=1), entity_id=eid)
    assert stats.ok == 1 and stats.failed == 0
    row = (
        session.execute(
            text(
                "SELECT version, status, card, pack_version FROM comprehension_cards "
                "WHERE entity_id = :e"
            ),
            {"e": eid},
        )
        .mappings()
        .one()
    )
    assert row["version"] == 1 and row["status"] == "ok" and row["pack_version"] == 1
    ComprehensionCard.model_validate(row["card"])  # stored card is schema-valid
    assert row["card"]["category_disputed"] is False  # mock category == rule category

    # A second run appends version 2 (old retained) — doc 05 §5.
    comp.run_comprehend(session, t0 + timedelta(days=2), entity_id=eid)
    versions = (
        session.execute(
            text("SELECT version FROM comprehension_cards WHERE entity_id = :e ORDER BY version"),
            {"e": eid},
        )
        .scalars()
        .all()
    )
    assert versions == [1, 2]


def test_category_disagreement_is_flagged_not_applied(clean_db: Session, monkeypatch) -> None:
    session = clean_db
    t0 = datetime(2024, 1, 1, tzinfo=UTC)
    eid = _entity(session, "proj", created=t0, category="inference-runtime", attrs={"text": "x"})
    session.flush()

    # Provider returns a card proposing a *different* category than the rule assigned.
    from decimal import Decimal

    from seismo.checkpoints.llm import LLMResult

    def fake_complete(system, user, schema, *, fallback, purpose="live"):
        return LLMResult(
            content=fallback | {"category": "agent-framework"}, model="fake", cost_usd=Decimal(0)
        )

    monkeypatch.setattr(comp, "complete_card", fake_complete)
    stats = comp.run_comprehend(session, t0 + timedelta(days=1), entity_id=eid)
    assert stats.category_disputes == 1
    card = session.execute(
        text("SELECT card FROM comprehension_cards WHERE entity_id = :e"), {"e": eid}
    ).scalar_one()
    assert card["category_disputed"] is True
    # The deterministic entity category is untouched — the model never overwrites it.
    from seismo.db import category_asof

    assert category_asof(session, eid, t0 + timedelta(days=1)) == "inference-runtime"


def test_budget_ceiling_marks_pending_without_calling(clean_db: Session, monkeypatch) -> None:
    session = clean_db
    t0 = datetime(2024, 1, 1, tzinfo=UTC)
    eid = _entity(session, "proj", created=t0, attrs={"text": "x"})
    session.flush()

    monkeypatch.setattr(settings, "llm_provider", "anthropic")
    monkeypatch.setattr(settings, "llm_budget_usd", 0.0)
    # If the budget gate failed, this would try to hit the network and raise.
    stats = comp.run_comprehend(session, t0 + timedelta(days=1), entity_id=eid)
    assert stats.pending == 1 and stats.ok == 0
    status = session.execute(
        text("SELECT status FROM comprehension_cards WHERE entity_id = :e"), {"e": eid}
    ).scalar_one()
    assert status == "pending"
