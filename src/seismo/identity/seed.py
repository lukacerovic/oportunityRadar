"""Seed universe loader (doc 14 §3) — ``seismo seed-load``.

The seed is a hand-curated inventory of entities that already matter on day 1 (doc 14 §3.1):
without it the system is blind to everything born before go-live and every category's cohort
starts empty. The loader emits ordinary ``raw_events`` (``source='seed'``, ``origin='seed'``,
``event_type='seed_anchor'``) — one per registry anchor — so from ``resolve`` onward a seed
entity is indistinguishable from a discovered one (doc 14 §2: same code paths, no bootstrap
engine). Each event carries its block's full anchor set so all of a block's registry anchors
resolve to a single entity.

Idempotent on ``(source='seed', source_event_uid='seed:<registry>:<native_id>')`` — re-running
inserts zero rows. **As-of note (doc 13 A-2):** seed events carry ``occurred_at = load date``,
so a seed loaded today is correctly invisible to any past hindcast ``as_of``; hindcasts use their
own ``origin='backfill'`` loaders and can exclude the ``seed`` origin entirely.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

import yaml
from pydantic import BaseModel, Field, field_validator
from sqlalchemy.orm import Session

from seismo.collectors.base import RawEventDraft
from seismo.identity.vocab import categories, themes

_DEFAULT_SEED = Path(__file__).resolve().parents[3] / "seed" / "seed_entities.yaml"

# Registry aliases used in the YAML for readability -> the canonical anchor registry.
_REGISTRY_ALIAS = {"hf_org": "hf", "hf_model": "hf", "gh": "github"}
_VALID_REGISTRIES = {"github", "pypi", "npm", "arxiv", "hf"}


class SeedEntity(BaseModel):
    name: str
    entity_type: str
    category: str
    anchors: dict[str, str]
    themes: list[str] = Field(default_factory=list)

    @field_validator("anchors")
    @classmethod
    def _normalize_anchors(cls, v: dict[str, str]) -> dict[str, str]:
        out: dict[str, str] = {}
        for reg, nid in v.items():
            canon = _REGISTRY_ALIAS.get(reg, reg)
            if canon not in _VALID_REGISTRIES:
                raise ValueError(f"unknown anchor registry {reg!r}")
            out[canon] = _norm_native_id(canon, str(nid))
        if not out:
            raise ValueError("seed entity has no anchors")
        return out


def _norm_native_id(registry: str, native_id: str) -> str:
    nid = native_id.strip()
    if registry in {"github", "hf"}:
        return nid.strip("/").lower()
    if registry in {"pypi", "npm"}:
        return nid.lower()
    return nid  # arxiv ids are case-sensitive-ish; leave as authored


@dataclass
class SeedStats:
    entities_in_file: int = 0
    events_emitted: int = 0
    events_new: int = 0


def load_seed_file(path: Path | None = None) -> list[SeedEntity]:
    """Parse + validate the seed YAML, and check every category/theme is in the vocabulary."""
    raw = yaml.safe_load((path or _DEFAULT_SEED).read_text()) or []
    entities = [SeedEntity.model_validate(block) for block in raw]
    known_cats = {c.slug for c in categories()}
    known_themes = set(themes())
    for e in entities:
        if e.category not in known_cats:
            raise ValueError(f"seed {e.name!r}: unknown category {e.category!r}")
        for t in e.themes:
            if t not in known_themes:
                raise ValueError(f"seed {e.name!r}: unknown theme {t!r}")
    return entities


def seed_drafts(entities: list[SeedEntity], *, load_date: datetime) -> list[RawEventDraft]:
    """Pure: one ``seed_anchor`` draft per (entity, registry anchor). Each draft carries the whole
    block's anchor set so attachment collapses all of a block's anchors into one entity."""
    drafts: list[RawEventDraft] = []
    for e in entities:
        for registry, native_id in e.anchors.items():
            drafts.append(
                RawEventDraft(
                    source="seed",
                    source_event_uid=f"seed:{registry}:{native_id}",
                    event_type="seed_anchor",
                    occurred_at=load_date,
                    origin="seed",
                    payload={
                        "anchor": {"registry": registry, "native_id": native_id},
                        "anchors": e.anchors,
                        "name": e.name,
                        "entity_type": e.entity_type,
                        "category": e.category,
                        "themes": e.themes,
                    },
                )
            )
    return drafts


def seed_load(
    session: Session, *, path: Path | None = None, now: datetime | None = None
) -> SeedStats:
    """Load the seed universe idempotently. Returns counts. Persists via the collector runner's
    ON CONFLICT DO NOTHING path, so re-running inserts zero events (doc 14 §3.3)."""
    from seismo.collectors.runner import persist_drafts

    load_date = now or datetime.now(UTC)
    entities = load_seed_file(path)
    drafts = seed_drafts(entities, load_date=load_date)
    new = persist_drafts(session, drafts)
    return SeedStats(entities_in_file=len(entities), events_emitted=len(drafts), events_new=new)
