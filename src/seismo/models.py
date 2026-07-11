"""SQLAlchemy 2.0 models mirroring the core schema (doc 02 §4, migration 0001).

Alembic owns the schema; these models are the ORM view of it. Keep them in sync with
migrations — never ``create_all`` in app code. Later stages add columns/tables via new
additive migrations (0002 = doc 13 A-2/A-4), and this file grows to match.
"""

from __future__ import annotations

from datetime import date, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import (
    REAL,
    BigInteger,
    Boolean,
    Date,
    DateTime,
    ForeignKey,
    Integer,
    Numeric,
    Text,
    func,
)
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


# --- Layer 1: immutable observations ---------------------------------------


class RawEvent(Base):
    __tablename__ = "raw_events"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    source: Mapped[str] = mapped_column(Text, nullable=False)
    source_event_uid: Mapped[str] = mapped_column(Text, nullable=False)
    event_type: Mapped[str] = mapped_column(Text, nullable=False)
    occurred_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    ingested_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    origin: Mapped[str] = mapped_column(Text, nullable=False, server_default="live")
    payload: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)


# --- Layer 2: durable things -----------------------------------------------


class Entity(Base):
    __tablename__ = "entities"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    entity_type: Mapped[str] = mapped_column(Text, nullable=False)
    canonical_name: Mapped[str] = mapped_column(Text, nullable=False)
    category: Mapped[str | None] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    merged_into: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("entities.id"))
    attrs: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False, server_default="{}")
    # A-4 bounded tracking (migration 0002): active | slow | archived.
    tracking_tier: Mapped[str] = mapped_column(Text, nullable=False, server_default="active")
    tier_reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class EntityLink(Base):
    __tablename__ = "entity_links"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    entity_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("entities.id"), nullable=False)
    raw_event_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("raw_events.id"))
    linked_entity_id: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("entities.id"))
    rule: Mapped[str] = mapped_column(Text, nullable=False)
    confidence: Mapped[float] = mapped_column(REAL, nullable=False)
    # A-2 (migration 0002): occurred_at of the justifying event, for as-of graph rebuilds.
    evidence_occurred_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class EntityMerge(Base):
    """Append-only, reversible merge record (doc 04 DR-04.2, doc 13 A-2). As-of code reads this,
    never ``entities.merged_into`` (which is a convenience denorm). A merge is visible at ``as_of``
    only when ``active AND justified_at <= as_of``."""

    __tablename__ = "entity_merges"

    loser_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("entities.id"), primary_key=True)
    survivor_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("entities.id"), nullable=False)
    justified_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    rule: Mapped[str] = mapped_column(Text, nullable=False)
    confidence: Mapped[float] = mapped_column(REAL, nullable=False)
    decided_by: Mapped[str] = mapped_column(Text, nullable=False)  # 'auto' | 'human'
    decided_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    active: Mapped[bool] = mapped_column(Boolean, nullable=False, server_default="true")


class EntityCategoryHistory(Base):
    """Time-versioned category (doc 13 A-2). Category drives cohorts/reach, so the value an
    entity had *at as_of* must be recoverable, not just its category today."""

    __tablename__ = "entity_category_history"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    entity_id: Mapped[int] = mapped_column(BigInteger, ForeignKey("entities.id"), nullable=False)
    category: Mapped[str] = mapped_column(Text, nullable=False)
    effective_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    evidence_event: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("raw_events.id"))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class EntityMergeQueue(Base):
    __tablename__ = "entity_merge_queue"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    entity_a: Mapped[int] = mapped_column(BigInteger, ForeignKey("entities.id"), nullable=False)
    entity_b: Mapped[int] = mapped_column(BigInteger, ForeignKey("entities.id"), nullable=False)
    confidence: Mapped[float] = mapped_column(REAL, nullable=False)
    evidence: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="pending")
    decided_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class Theme(Base):
    __tablename__ = "themes"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    name: Mapped[str] = mapped_column(Text, unique=True, nullable=False)
    description: Mapped[str | None] = mapped_column(Text)


class EntityTheme(Base):
    __tablename__ = "entity_themes"

    entity_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    theme_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    source: Mapped[str | None] = mapped_column(Text)
    # A-2 (migration 0002): when the assignment became true, for as-of theme rebuilds.
    effective_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


# --- Layers 3–6 outputs -----------------------------------------------------


class ComprehensionCard(Base):
    __tablename__ = "comprehension_cards"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    entity_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    card: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    model: Mapped[str] = mapped_column(Text, nullable=False)
    cost_usd: Mapped[Decimal | None] = mapped_column(Numeric(8, 4))
    # ok | pending (budget ceiling, A-12) | failed (validation error after retry, DR-05.2).
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="ok")
    pack_version: Mapped[int | None] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class EntityMetricDaily(Base):
    __tablename__ = "entity_metrics_daily"

    entity_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    metric: Mapped[str] = mapped_column(Text, primary_key=True)
    day: Mapped[date] = mapped_column(Date, primary_key=True)
    value: Mapped[Decimal] = mapped_column(Numeric, nullable=False)


class MaturityPromotion(Base):
    __tablename__ = "maturity_promotions"

    entity_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    stage: Mapped[str] = mapped_column(Text, primary_key=True)
    promoted_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    evidence_event: Mapped[int | None] = mapped_column(BigInteger, ForeignKey("raw_events.id"))


class MomentumState(Base):
    __tablename__ = "momentum_states"

    entity_id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    day: Mapped[date] = mapped_column(Date, primary_key=True)
    state: Mapped[str] = mapped_column(Text, nullable=False)
    score: Mapped[Decimal | None] = mapped_column(Numeric)
    inputs: Mapped[dict[str, Any] | None] = mapped_column(JSONB)


class GateDecision(Base):
    __tablename__ = "gate_decisions"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    entity_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    week: Mapped[date] = mapped_column(Date, nullable=False)
    decision: Mapped[str] = mapped_column(Text, nullable=False)
    score: Mapped[Decimal] = mapped_column(Numeric, nullable=False)
    components: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class ImpactBrief(Base):
    __tablename__ = "impact_briefs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    entity_id: Mapped[int] = mapped_column(BigInteger, nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    as_of: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    brief: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    status: Mapped[str] = mapped_column(Text, nullable=False, server_default="draft")
    model: Mapped[str | None] = mapped_column(Text)
    cost_usd: Mapped[Decimal | None] = mapped_column(Numeric(8, 4))
    reviewed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), server_default=func.now())


class BriefScore(Base):
    __tablename__ = "brief_scores"

    brief_id: Mapped[int] = mapped_column(
        BigInteger, ForeignKey("impact_briefs.id"), primary_key=True
    )
    scored_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    materialized: Mapped[str | None] = mapped_column(Text)
    falsifier_tripped: Mapped[bool | None] = mapped_column(Boolean)
    notes: Mapped[str | None] = mapped_column(Text)


# --- Exposure map (loaded from YAML, doc 08) --------------------------------


class ExposureCompany(Base):
    __tablename__ = "exposure_companies"

    ticker: Mapped[str] = mapped_column(Text, primary_key=True)
    name: Mapped[str | None] = mapped_column(Text)
    sector: Mapped[str | None] = mapped_column(Text)
    doc: Mapped[dict[str, Any]] = mapped_column(JSONB, nullable=False)
    loaded_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))


class ReachLink(Base):
    __tablename__ = "reach_links"

    category: Mapped[str] = mapped_column(Text, primary_key=True)
    ticker: Mapped[str] = mapped_column(Text, primary_key=True)
    revenue_line: Mapped[str] = mapped_column(Text, primary_key=True)
    relation: Mapped[str] = mapped_column(Text, primary_key=True)


# --- Bookkeeping ------------------------------------------------------------


class CollectorRun(Base):
    __tablename__ = "collector_runs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    source: Mapped[str | None] = mapped_column(Text)
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ok: Mapped[bool | None] = mapped_column(Boolean)
    events_new: Mapped[int | None] = mapped_column(Integer)
    error: Mapped[str | None] = mapped_column(Text)


class PipelineRun(Base):
    __tablename__ = "pipeline_runs"

    id: Mapped[int] = mapped_column(BigInteger, primary_key=True)
    stage: Mapped[str | None] = mapped_column(Text)
    as_of: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    started_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    finished_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True))
    ok: Mapped[bool | None] = mapped_column(Boolean)
    notes: Mapped[str | None] = mapped_column(Text)


__all__ = [
    "Base",
    "RawEvent",
    "Entity",
    "EntityLink",
    "EntityMerge",
    "EntityCategoryHistory",
    "EntityMergeQueue",
    "Theme",
    "EntityTheme",
    "ComprehensionCard",
    "EntityMetricDaily",
    "MaturityPromotion",
    "MomentumState",
    "GateDecision",
    "ImpactBrief",
    "BriefScore",
    "ExposureCompany",
    "ReachLink",
    "CollectorRun",
    "PipelineRun",
]
