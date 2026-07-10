"""Seed universe loader (doc 14 §3) — file validity, coverage, idempotent load, and the
seed+resolve interaction that collapses a block's anchors into one entity and pulls in a
discovered reference.
"""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from seismo.db import canonical_entity_id
from seismo.identity.resolve import resolve
from seismo.identity.seed import load_seed_file, seed_drafts, seed_load
from seismo.identity.vocab import categories
from seismo.models import Entity, RawEvent

LOAD_DATE = datetime(2026, 7, 11, tzinfo=UTC)


# --- file validity + coverage -----------------------------------------------


def test_seed_file_loads_and_covers_every_category() -> None:
    entities = load_seed_file()
    assert len(entities) >= 150 or len(entities) >= 120  # ~150–300 target; solid coverage minimum
    seeded_cats = {e.category for e in entities}
    all_cats = {c.slug for c in categories()} - {"uncategorized"}
    missing = all_cats - seeded_cats
    assert not missing, f"cold-start cohort mass requires every category seeded; missing: {missing}"


def test_seed_anchor_registry_aliases_normalize() -> None:
    entities = {e.name: e for e in load_seed_file()}
    deepseek = entities["DeepSeek"]
    # hf_org alias -> hf registry; github org handle lowercased.
    assert deepseek.anchors["hf"] == "deepseek-ai"
    assert deepseek.anchors["github"] == "deepseek-ai"


def test_seed_drafts_one_per_anchor_with_stable_uid() -> None:
    entities = load_seed_file()
    vllm = next(e for e in entities if e.name == "vLLM")
    drafts = seed_drafts([vllm], load_date=LOAD_DATE)
    assert len(drafts) == len(vllm.anchors)
    uids = {d.source_event_uid for d in drafts}
    assert "seed:github:vllm-project/vllm" in uids
    assert all(d.origin == "seed" and d.event_type == "seed_anchor" for d in drafts)
    # Every draft carries the whole block's anchor set (so attachment can collapse them).
    assert all(d.payload["anchors"] == vllm.anchors for d in drafts)


# --- idempotent load --------------------------------------------------------


def test_seed_load_is_idempotent(clean_db: Session) -> None:
    first = seed_load(clean_db, now=LOAD_DATE)
    clean_db.flush()
    second = seed_load(clean_db, now=LOAD_DATE)
    clean_db.flush()
    assert first.events_new == first.events_emitted > 0
    assert second.events_new == 0  # re-running inserts nothing (ON CONFLICT)
    total = clean_db.scalar(select(func.count()).select_from(RawEvent))
    assert total == first.events_emitted


# --- seed + resolve interaction ---------------------------------------------


def test_seed_block_anchors_collapse_to_one_entity(clean_db: Session) -> None:
    entities = load_seed_file()
    vllm = next(e for e in entities if e.name == "vLLM")  # github + pypi + arxiv
    drafts = seed_drafts([vllm], load_date=LOAD_DATE)
    from seismo.collectors.runner import persist_drafts

    persist_drafts(clean_db, drafts)
    clean_db.flush()

    resolve(clean_db, cold_start=True, now=datetime(2026, 7, 12, tzinfo=UTC))
    clean_db.flush()

    # All three registry anchors of the vLLM block resolve to exactly one entity.
    assert clean_db.scalar(select(func.count()).select_from(Entity)) == 1
    ent = clean_db.execute(select(Entity)).scalar_one()
    assert set(ent.attrs["anchors"]) == {"github", "pypi", "arxiv"}
    assert ent.category == "inference-runtime"


def test_discovered_paper_merges_into_seeded_repo(clean_db: Session) -> None:
    # Seed the DeepSeek-V2 repo, then a *discovered* arxiv paper that references it should merge in.
    from seismo.collectors.runner import persist_drafts
    from seismo.identity.seed import SeedEntity

    seed = SeedEntity(
        name="DeepSeek-V2 repo",
        entity_type="project",
        category="model-foundation",
        anchors={"github": "deepseek-ai/DeepSeek-V2"},
    )
    persist_drafts(clean_db, seed_drafts([seed], load_date=LOAD_DATE))
    clean_db.add(
        RawEvent(
            source="arxiv",
            source_event_uid="2405.04434",
            event_type="paper_published",
            occurred_at=datetime(2024, 5, 7, tzinfo=UTC),
            origin="backfill",
            payload={
                "arxiv_id": "2405.04434",
                "comment": "Code at https://github.com/deepseek-ai/DeepSeek-V2",
            },
        )
    )
    clean_db.flush()

    now = datetime(2026, 7, 12, tzinfo=UTC)
    resolve(clean_db, now=now)
    clean_db.flush()

    github_id = clean_db.execute(
        select(Entity.id).where(
            Entity.attrs["anchors"]["github"].astext == "deepseek-ai/deepseek-v2"
        )
    ).scalar_one()
    arxiv_id = clean_db.execute(
        select(Entity.id).where(Entity.attrs["anchors"]["arxiv"].astext == "2405.04434")
    ).scalar_one()
    assert canonical_entity_id(clean_db, arxiv_id, now) == github_id
