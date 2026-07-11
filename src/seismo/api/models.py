"""Pydantic response models for the read + curation API (doc 10 §1).

These are the contract the Next.js dashboard consumes — the OpenAPI schema they generate is what
``openapi-typescript`` turns into the TS client, so the two codebases can't drift silently. Every
read model is a projection of the as-of knowledge graph; the dashboard never touches Postgres.
"""

from __future__ import annotations

from datetime import date, datetime
from typing import Any

from pydantic import BaseModel


class SparkPoint(BaseModel):
    day: date
    value: float


class RadarEntity(BaseModel):
    """One tile on the Radar grid (doc 10 §2)."""

    id: int
    name: str
    entity_type: str
    category: str | None
    state: str  # momentum state; drives the fixed 5-colour scale
    velocity_pctl: float | None  # composite P, 0..1
    maturity_stage: str | None
    one_liner: str | None  # latest card what_it_is
    provisional: bool  # cold-start thin cohort (doc 14 §5)
    sparkline: list[float]  # last 30d of the headline metric, oldest→newest


class RadarResponse(BaseModel):
    as_of: datetime
    count: int
    entities: list[RadarEntity]


class MaturityRung(BaseModel):
    stage: str
    promoted_at: datetime


class MetricSeries(BaseModel):
    metric: str
    points: list[SparkPoint]


class MomentumPoint(BaseModel):
    day: date
    state: str
    score: float | None


class Card(BaseModel):
    """A comprehension card version (doc 05 §1) as stored, plus its envelope."""

    version: int
    as_of: datetime
    status: str  # ok | pending | failed
    model: str
    what_it_is: str | None = None
    function: str | None = None
    claimed_advantage: str | None = None
    replaces_or_enables: list[str] = []
    maturity_stage: str | None = None
    who_is_behind: str | None = None
    open_questions: list[str] = []
    confidence: str | None = None
    category: str | None = None
    category_disputed: bool = False


class EntityDossier(BaseModel):
    """The full `/entity/[id]` view (doc 10 §2)."""

    id: int
    name: str
    entity_type: str
    category: str | None
    anchors: dict[str, str]
    owner: str | None
    first_seen: date
    tracking_tier: str
    state: str
    velocity_pctl: float | None
    provisional: bool
    cohort_n: int | None
    maturity: list[MaturityRung]
    metrics: list[MetricSeries]
    momentum_history: list[MomentumPoint]
    card: Card | None
    card_versions: list[int]


class MiniEntity(BaseModel):
    id: int
    name: str
    entity_type: str
    category: str | None
    owner: str | None


class QueueItem(BaseModel):
    """One merge-queue pair awaiting human triage (doc 10 §2 `/queue`)."""

    id: int
    entity_a: MiniEntity
    entity_b: MiniEntity
    confidence: float
    evidence: dict[str, Any]
    status: str


class SearchHit(BaseModel):
    id: int
    name: str
    entity_type: str
    category: str | None
    state: str | None


class HealthCheck(BaseModel):
    name: str
    ok: bool
    detail: str


class HealthResponse(BaseModel):
    ok: bool
    checks: list[HealthCheck]


class DecisionResult(BaseModel):
    id: int
    status: str
    merged: bool
