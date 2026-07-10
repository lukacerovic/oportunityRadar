"""The resolution engine end-to-end (doc 04 §1–5) against real Postgres (rolled back).

Centerpiece: the Stage-2 DoD hindcast — a DeepSeek paper + GitHub repo + HF model resolve into
one canonical entity via R1/R2 only.
"""

from __future__ import annotations

from datetime import UTC, datetime

import pytest
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from seismo.db import canonical_entity_id
from seismo.identity.resolve import resolve
from seismo.models import Entity, EntityMerge, EntityMergeQueue, RawEvent

NOW = datetime(2026, 7, 1, tzinfo=UTC)

# Tables to clear so each test runs against an isolated slate. resolve() is global by design and
# the shared dev DB carries committed Stage-1 events; deletions live inside the rolled-back
# transaction, so real data is restored when the test's transaction rolls back. Order = dependents
# before the entities/raw_events they reference.
_CLEAR = [
    "entity_merge_queue",
    "entity_merges",
    "entity_category_history",
    "entity_themes",
    "entity_links",
    "momentum_states",
    "maturity_promotions",
    "entity_metrics_daily",
    "comprehension_cards",
    "gate_decisions",
    "brief_scores",
    "impact_briefs",
    "entities",
    "raw_events",
]


@pytest.fixture(autouse=True)
def _isolated(db_session: Session) -> Session:
    for table in _CLEAR:
        db_session.execute(text(f"DELETE FROM {table}"))
    db_session.flush()
    return db_session


def _event(
    session: Session, source: str, uid: str, etype: str, payload: dict, when: datetime
) -> None:
    session.add(
        RawEvent(
            source=source,
            source_event_uid=uid,
            event_type=etype,
            occurred_at=when,
            origin="backfill",
            payload=payload,
        )
    )


def _entity_by_anchor(session: Session, key: str) -> int:
    reg, nid = key.split(":", 1)
    row = session.execute(
        select(Entity.id).where(Entity.attrs["anchors"][reg].astext == nid)
    ).scalar_one()
    return int(row)


# --- DoD: DeepSeek resolves to one entity via R1/R2 -------------------------


def test_deepseek_backfill_resolves_to_one_entity(db_session: Session) -> None:
    # GitHub repo created first (so it becomes the surviving canonical entity).
    _event(
        db_session,
        "github",
        "repo_discovered:1",
        "repo_discovered",
        {"full_name": "deepseek-ai/DeepSeek-V2", "description": "DeepSeek-V2 MoE model"},
        datetime(2024, 5, 6, tzinfo=UTC),
    )
    _event(
        db_session,
        "arxiv",
        "2405.04434",
        "paper_published",
        {
            "arxiv_id": "2405.04434",
            "title": "DeepSeek-V2",
            "comment": "Code at https://github.com/deepseek-ai/DeepSeek-V2",
        },
        datetime(2024, 5, 7, tzinfo=UTC),
    )
    _event(
        db_session,
        "hf",
        "deepseek-ai/DeepSeek-V2",
        "model_discovered",
        {"id": "deepseek-ai/DeepSeek-V2", "tags": ["arxiv:2405.04434"]},
        datetime(2024, 5, 8, tzinfo=UTC),
    )
    db_session.flush()

    stats = resolve(db_session, now=NOW)
    db_session.flush()

    assert stats.entities_created == 3
    assert stats.auto_merges == 2  # paper->repo (R2), hf->repo (R2, transitively)

    github_id = _entity_by_anchor(db_session, "github:deepseek-ai/deepseek-v2")
    arxiv_id = _entity_by_anchor(db_session, "arxiv:2405.04434")
    hf_id = _entity_by_anchor(db_session, "hf:deepseek-ai/deepseek-v2")
    roots = {canonical_entity_id(db_session, e, NOW) for e in (github_id, arxiv_id, hf_id)}
    assert roots == {github_id}, "all three registries must collapse to the GitHub project"

    # Only R1/R2 fired the merges (DoD wording).
    rules = set(db_session.scalars(select(EntityMerge.rule)))
    assert rules <= {"R1", "R2"}


def test_resolve_is_idempotent(db_session: Session) -> None:
    _event(
        db_session,
        "github",
        "repo_discovered:1",
        "repo_discovered",
        {"full_name": "deepseek-ai/DeepSeek-V2"},
        datetime(2024, 5, 6, tzinfo=UTC),
    )
    _event(
        db_session,
        "arxiv",
        "2405.04434",
        "paper_published",
        {"arxiv_id": "2405.04434", "comment": "https://github.com/deepseek-ai/DeepSeek-V2"},
        datetime(2024, 5, 7, tzinfo=UTC),
    )
    db_session.flush()

    first = resolve(db_session, now=NOW)
    db_session.flush()
    second = resolve(db_session, now=NOW)
    db_session.flush()

    assert first.entities_created == 2 and first.auto_merges == 1
    assert second.entities_created == 0 and second.auto_merges == 0 and second.queued == 0
    assert db_session.scalar(select(func.count()).select_from(EntityMerge)) == 1


# --- R4 queue (owner + name) ------------------------------------------------


def test_owner_plus_name_goes_to_queue_not_merge(db_session: Session) -> None:
    # Same owner + same normalized name across github and hf → R4 (0.85) → queue, never merged.
    _event(
        db_session,
        "github",
        "repo_discovered:2",
        "repo_discovered",
        {"full_name": "bigscience/bloom"},
        datetime(2024, 1, 1, tzinfo=UTC),
    )
    _event(
        db_session,
        "hf",
        "bigscience/bloom",
        "model_discovered",
        {"id": "bigscience/bloom"},
        datetime(2024, 1, 2, tzinfo=UTC),
    )
    db_session.flush()

    stats = resolve(db_session, now=NOW)
    db_session.flush()

    assert stats.auto_merges == 0
    assert stats.queued == 1
    q = db_session.execute(select(EntityMergeQueue)).scalar_one()
    assert q.status == "pending"
    assert q.evidence["rule"] == "R4"


def test_cold_start_defers_name_rules(db_session: Session) -> None:
    _event(
        db_session,
        "github",
        "repo_discovered:2",
        "repo_discovered",
        {"full_name": "bigscience/bloom"},
        datetime(2024, 1, 1, tzinfo=UTC),
    )
    _event(
        db_session,
        "hf",
        "bigscience/bloom",
        "model_discovered",
        {"id": "bigscience/bloom"},
        datetime(2024, 1, 2, tzinfo=UTC),
    )
    db_session.flush()

    stats = resolve(db_session, cold_start=True, now=NOW)
    db_session.flush()

    assert stats.queued == 0 and stats.queued_deferred == 1
    q = db_session.execute(select(EntityMergeQueue)).scalar_one()
    assert q.status == "deferred_coldstart"


# --- attachment: HN with no link is unowned ---------------------------------


def test_hn_story_without_registry_link_is_unowned(db_session: Session) -> None:
    _event(
        db_session,
        "hn",
        "hn1",
        "story",
        {"title": "a new LLM agent", "url": "https://blog.example.com"},
        datetime(2024, 6, 1, tzinfo=UTC),
    )
    db_session.flush()
    stats = resolve(db_session, now=NOW)
    db_session.flush()
    assert stats.entities_created == 0 and stats.events_attached == 0


def test_hn_story_with_github_link_attaches(db_session: Session) -> None:
    _event(
        db_session,
        "hn",
        "hn2",
        "story",
        {"title": "Show HN: vLLM", "url": "https://github.com/vllm-project/vllm"},
        datetime(2024, 6, 1, tzinfo=UTC),
    )
    db_session.flush()
    stats = resolve(db_session, now=NOW)
    db_session.flush()
    assert stats.entities_created == 1 and stats.events_attached == 1
    assert _entity_by_anchor(db_session, "github:vllm-project/vllm")


# --- category assignment ----------------------------------------------------


def test_category_assigned_and_history_recorded(db_session: Session) -> None:
    _event(
        db_session,
        "github",
        "repo_discovered:3",
        "repo_discovered",
        {"full_name": "x/fastserve", "description": "high-throughput LLM inference server"},
        datetime(2024, 3, 1, tzinfo=UTC),
    )
    db_session.flush()
    resolve(db_session, now=NOW)
    db_session.flush()
    ent = db_session.execute(
        select(Entity).where(Entity.canonical_name == "x/fastserve")
    ).scalar_one()
    assert ent.category == "inference-runtime"
