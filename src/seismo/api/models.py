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
    sources: list[str]  # collectors that touched it: github/hn/arxiv/hf/seed/…
    gated: bool  # has ever passed the weekly significance gate (queued for/got a brief)


class GraphNode(BaseModel):
    """One node in the correlation graph — a tracked entity, or a concept an LLM pass named
    (e.g. "Claude Code", "MCP") that isn't itself a tracked entity."""

    id: str  # "e:<entity_id>" for entities, "c:<slug>" for bare concepts
    label: str
    kind: str  # entity | concept
    category: str | None = None
    entity_id: int | None = None  # None for a concept node
    seed: bool = False  # gated or breakout/accelerating — the "why this is on screen" signal
    # person/org nodes (Wikidata team enrichment) have no category — the dashboard styles them
    # by this instead, so the team layer reads distinctly from projects/papers/models.
    entity_type: str | None = None
    # attrs['wikidata'] display card (description, website, HQ, industry, awards, dates) —
    # rendered in the node panel on click; None for nodes without Wikidata enrichment.
    info: dict[str, Any] | None = None


class GraphEdge(BaseModel):
    """One edge — either from the deterministic spine (`entity_graph_edges`, every row justified
    by a raw_event) or the LLM-reasoned relation graph (`entity_semantic_edges`, a model's
    judgement). `kind` is what a consumer must check before trusting an edge as fact."""

    source: str
    target: str
    relation: str
    kind: str  # deterministic | reasoned
    weight: float = 1.0


class GraphResponse(BaseModel):
    nodes: list[GraphNode]
    edges: list[GraphEdge]


class GraphExplanationResponse(BaseModel):
    """AI-narrated context for one entity's relationship subgraph (migration 0013) — the
    dashboard's explanation side panel. ``stale`` means enrichment changed the subgraph since
    the text was written; the next ``explain-graphs`` run will rewrite it."""

    entity_id: int
    entity_name: str
    overview: str
    key_people: str
    organizations: str
    industry_context: str = ""  # broader background, explicitly model knowledge not graph data
    signals: str
    model: str
    updated_at: datetime
    node_count: int
    edge_count: int
    stale: bool = False


class RadarResponse(BaseModel):
    as_of: datetime
    count: int
    entities: list[RadarEntity]
    source_counts: dict[str, int] = {}  # entities per collection source, whole visible universe
    gated_count: int = 0  # entities that have ever passed the gate, whole visible universe


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


class EvidenceItem(BaseModel):
    """One human-readable piece of evidence attached to an entity — a source you can open and read
    (the HN story, the project repo, the paper, the fetched launch/README text)."""

    source: str  # raw collector source: hn | github | arxiv | hf | web | seed | openrouter
    kind: str  # display label, e.g. "Hacker News", "arXiv paper", "Launch page", "README"
    title: str | None
    url: str | None  # a link the reader can open
    text: str | None  # readable content: abstract, launch-page / README body (truncated)
    score: int | None  # attention/usage number for this item (HN points, HF downloads, OR tokens)
    unit: str | None = None  # what `score` counts — "points"/"downloads"/"tokens"; None if no score
    occurred_at: datetime


class RelatedEntity(BaseModel):
    """One `entity_semantic_edges` neighbor — an LLM's judgement, never a rule's. `entity_id` is
    None when the other side is a bare concept (e.g. "Claude Code"), not a tracked entity."""

    label: str
    entity_id: int | None
    category: str | None
    relation: str  # semantically_similar_to | conceptually_related_to
    confidence_score: float


class CommunityThread(BaseModel):
    title: str
    source: str = ""  # github | hn | hf
    channel: str = ""  # "GitHub Issues", "Hacker News", "HF Discussions"
    url: str
    score: int | None = None
    comment_count: int | None = None
    created_at: datetime | None = None
    relevance_score: float | None = None
    comments: list[str] = []  # the actual discussion text collected from the thread


class CommunityResearch(BaseModel):
    source: str  # github | hf | hn | summary (the cross-source AI verdict)
    status: str
    summary: str
    sentiment: str | None = None
    sentiment_score: int | None = None  # 0-100, set on the 'summary' verdict row
    confidence: str | None = None
    main_points: list[str] = []
    concerns: list[str] = []
    positive_signals: list[str] = []
    notable_quotes: list[str] = []  # representative comments, on the 'summary' verdict row
    kpis: dict[str, Any] | None = None  # {sources, thread_count, comment_count}, verdict row
    threads: list[CommunityThread] = []
    researched_at: datetime


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
    description: str | None  # aggregated readable text we've collected about it
    themes: list[str]  # research/market themes this entity belongs to
    maturity: list[MaturityRung]
    metrics: list[MetricSeries]
    momentum_history: list[MomentumPoint]
    evidence: list[EvidenceItem]  # sources you can open and read
    related: list[RelatedEntity] = []  # entity_semantic_edges neighbors, highest confidence first
    community: list[CommunityResearch] = []  # latest community-opinion analysis per source
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


# --- significance gate (doc 07 §3 — the audit page) -------------------------


class GateComponents(BaseModel):
    """The M×R×N breakdown stored on a `gate_decisions` row — why it passed or was suppressed."""

    M: float | None = None
    R: float | None = None
    N: float | None = None
    score: float | None = None
    peak_state: str | None = None
    p_peak: float | None = None
    category: str | None = None
    reach_lines: int | None = None
    reach_core: bool | None = None
    reason: str | None = None  # unmapped_reach | card_pending | budget (suppressed only)


class GateDecisionItem(BaseModel):
    entity_id: int
    name: str
    entity_type: str
    category: str | None
    decision: str  # pass | suppressed
    score: float
    components: GateComponents


class GateWeekResponse(BaseModel):
    """One week's gate audit (doc 07 §3): the passed list, the suppressed list with reasons, and
    the map-gaps that unmapped-reach suppressions rolled up into."""

    week: date
    briefs_budget: int
    passed: list[GateDecisionItem]
    suppressed: list[GateDecisionItem]
    map_gaps: dict[str, int]
    available_weeks: list[str]  # ISO weeks that have decisions, newest first (for navigation)


# --- impact brief (doc 08 §2 — the review page) -----------------------------


class BriefTransmissionStep(BaseModel):
    from_node: str
    to_node: str
    effect: str


class BriefObservable(BaseModel):
    statement: str
    source: str  # system | manual
    system_metric: str | None = None
    horizon: str
    direction_if_thesis_holds: str  # up | down | flat


class BriefExposure(BaseModel):
    kind: str  # ticker | sector_class
    ref: str
    revenue_line: str | None = None
    direction: str  # negative | positive | ambiguous
    magnitude_class: str  # marginal | material | structural


class CouncilVerdictItem(BaseModel):
    """One independent perspective's judgement on this brief (doc 08 §5)."""

    role: str  # skeptic | evidence_auditor | mechanism_reviewer
    stance: str  # adopt | watch | reject
    confidence: str  # low | med | high
    reasoning: str
    model: str


class Brief(BaseModel):
    """One impact-brief version (doc 08 §2) as stored, plus its review envelope."""

    id: int
    entity_id: int
    entity_name: str
    version: int
    as_of: datetime
    status: str  # draft | published | rejected | failed | pending
    model: str | None
    reviewed_at: datetime | None
    reject_reason: str | None = None
    entity_ref: str | None = None
    mechanisms: list[str] = []
    transmission_path: list[BriefTransmissionStep] = []
    exposures: list[BriefExposure] = []
    counter_mechanism: str | None = None
    observables: list[BriefObservable] = []
    confidence: str | None = None
    horizon: str | None = None
    summary: str | None = None
    evidence_refs: list[int] = []
    versions: list[int] = []  # all versions for this entity, newest first
    council: list[CouncilVerdictItem] = []  # empty unless this version went through council review
    council_stance: str | None = None  # deterministic majority vote; None until 3 verdicts exist


class BriefListItem(BaseModel):
    """One row in the review inbox (doc 08 §4)."""

    id: int
    entity_id: int
    entity_name: str
    version: int
    status: str
    as_of: datetime
    created_at: datetime
    mechanisms: list[str] = []
    n_exposures: int = 0
    summary: str | None = None


class BriefDecisionResult(BaseModel):
    id: int
    status: str


# --- memory & synthesis (doc 09) --------------------------------------------


class ChangeItem(BaseModel):
    kind: str
    entity_id: int | None
    text: str
    payload: dict[str, Any] = {}
    category: str | None = None


class ChangesResponse(BaseModel):
    """One day's deterministic Changes view (doc 09 §1), grouped by kind for rendering."""

    day: date
    groups: dict[str, list[ChangeItem]]  # kind → items, in a fixed display order
    total: int
    available_days: list[str]  # ISO dates that have changes, newest first


class CalibrationPoint(BaseModel):
    day: date
    value: float | None
    sample_n: int


class CalibrationResponse(BaseModel):
    """The momentum-call calibration track record (doc 09 §3), per metric over time."""

    series: dict[str, list[CalibrationPoint]]  # metric → points oldest→newest
    latest: dict[str, CalibrationPoint]


class ObservableEvalModel(BaseModel):
    statement: str
    source: str
    system_metric: str | None
    direction_if_thesis_holds: str
    status: str  # on_track | counter | flat | too_early | unmeasurable | operator_judgment
    detail: str


class ExistingScore(BaseModel):
    materialized: str | None = None
    falsifier_tripped: bool | None = None
    verdict: str | None = None
    counter_was_better: bool | None = None
    falsifier_observable: str | None = None


class ScorePacketResponse(BaseModel):
    """The quarterly scoring screen for one brief (doc 09 §2): the brief + its observables auto-
    evaluated (A-7) + since-publication metric history, ready for the operator's verdict."""

    brief_id: int
    entity_id: int
    entity_name: str
    version: int
    published_at: datetime | None
    horizon: str | None
    days_elapsed: int
    summary: str | None
    counter_mechanism: str | None
    exposures: list[BriefExposure]
    observable_evals: list[ObservableEvalModel]
    metric_history: dict[str, list[list[Any]]]  # metric → [[day_iso, value], …]
    auto_summary: str
    existing_score: ExistingScore | None


class ScoreResult(BaseModel):
    brief_id: int
    materialized: str
