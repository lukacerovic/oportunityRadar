"""FastAPI read + curation API (doc 10 §1) — the *only* door to the knowledge graph.

The dashboard never touches Postgres; every projection goes through here, which keeps the ``as_of``
discipline in one place (all read endpoints accept ``as_of`` for time-travel). Reads are open;
curation (non-GET) requires the static bearer token (DR-10.2). Pydantic models everywhere so the
OpenAPI schema generates a drift-proof TS client.
"""

from __future__ import annotations

import re
from collections.abc import Iterator
from datetime import UTC, date, datetime, timedelta
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from sqlalchemy.orm import Session

from seismo.api import models as m
from seismo.checkpoints.council_vote import aggregate_stance
from seismo.config import settings
from seismo.db import canonical_entity_id, category_asof, session_scope
from seismo.health import run_checks

app = FastAPI(title="Seismograph API", version="0.1.0")
app.add_middleware(
    CORSMiddleware,
    # The configured prod origin, plus any localhost port (Next dev may land on 3000/3001/…).
    allow_origins=[settings.dashboard_origin],
    allow_origin_regex=r"http://(localhost|127\.0\.0\.1):\d+",
    allow_methods=["*"],
    allow_headers=["*"],
)

_STATE_RANK = {"breakout": 0, "accelerating": 1, "simmering": 2, "fading": 3, "dormant": 4}
_HEADLINE_METRIC = "gh_stars"


# --- dependencies -----------------------------------------------------------


def get_session() -> Iterator[Session]:
    with session_scope() as session:
        yield session


def get_as_of(as_of: str | None = Query(None, description="ISO datetime; default now")) -> datetime:
    if as_of is None:
        return datetime.now(UTC)
    dt = datetime.fromisoformat(as_of)
    return dt if dt.tzinfo else dt.replace(tzinfo=UTC)


def require_token(authorization: str | None = Header(None)) -> None:
    """Static-bearer gate for curation endpoints (DR-10.2). Empty token = open (local dev)."""
    if not settings.api_token:
        return
    if authorization != f"Bearer {settings.api_token}":
        raise HTTPException(status_code=401, detail="invalid or missing bearer token")


# --- health -----------------------------------------------------------------


@app.get("/health", response_model=m.HealthResponse)
def health() -> m.HealthResponse:
    checks = [m.HealthCheck(name=c.name, ok=c.ok, detail=c.detail) for c in run_checks()]
    return m.HealthResponse(ok=all(c.ok for c in checks), checks=checks)


# --- radar ------------------------------------------------------------------


@app.get("/radar", response_model=m.RadarResponse)
def radar(
    session: Session = Depends(get_session),
    as_of: datetime = Depends(get_as_of),
    theme: str | None = Query(None),
    state: str | None = Query(None),
    source: str | None = Query(None),
    gated: bool = Query(False, description="Only entities that have ever passed the gate."),
    limit: int = Query(200, le=1000),
) -> m.RadarResponse:
    """Momentum-ranked entity grid: breakout → dormant, then velocity (doc 10 §2)."""
    rows = (
        session.execute(
            text(
                """
            WITH ms AS (
                SELECT DISTINCT ON (entity_id) entity_id, state, score, inputs
                FROM momentum_states WHERE day <= :as_of_day
                ORDER BY entity_id, day DESC
            ),
            lc AS (
                SELECT DISTINCT ON (entity_id) entity_id, card
                FROM comprehension_cards WHERE as_of <= :as_of AND status = 'ok'
                ORDER BY entity_id, version DESC
            ),
            src AS (
                -- Collectors that have touched each entity (github/hn/arxiv/hf/…),
                -- via the immutable events attached to it. HN only appears here.
                SELECT l.entity_id, array_agg(DISTINCT r.source) AS sources
                FROM entity_links l
                JOIN raw_events r ON r.id = l.raw_event_id
                WHERE l.rule = 'attach' AND r.occurred_at <= :as_of
                GROUP BY l.entity_id
            ),
            gp AS (
                -- Ever passed the weekly significance gate, as of a week visible by :as_of_day —
                -- a hindcast can't see a future week's gate pass (invariant 2).
                SELECT DISTINCT entity_id FROM gate_decisions
                WHERE decision = 'pass' AND week <= :as_of_day
            )
            SELECT e.id, e.canonical_name, e.entity_type, e.category,
                   COALESCE(ms.state, 'dormant') AS state, ms.inputs, lc.card,
                   COALESCE(src.sources, ARRAY[]::text[]) AS sources,
                   (gp.entity_id IS NOT NULL) AS gated
            FROM entities e
            LEFT JOIN ms ON ms.entity_id = e.id
            LEFT JOIN lc ON lc.entity_id = e.id
            LEFT JOIN src ON src.entity_id = e.id
            LEFT JOIN gp ON gp.entity_id = e.id
            """
                + (
                    "JOIN entity_themes et ON et.entity_id = e.id "
                    "JOIN themes th ON th.id = et.theme_id AND th.name = :theme "
                    if theme
                    else ""
                )
                + """
            WHERE e.merged_into IS NULL AND e.tracking_tier <> 'archived'
            """
                + ("AND COALESCE(ms.state, 'dormant') = :state " if state else "")
                + ("AND gp.entity_id IS NOT NULL " if gated else "")
                + (
                    # Filter by ORIGIN, not "any event that touched it": an entity belongs to the
                    # registry it is anchored on. HN stories attach to the github/arxiv/hf thing
                    # they link to, so those stay under their own source; only HN-native launches
                    # (anchored `web`) show under Hacker News. Mutually exclusive buckets.
                    "AND e.attrs->'anchors' ? :source_reg "
                    if source
                    else ""
                )
                + """
            ORDER BY CASE COALESCE(ms.state, 'dormant')
                       WHEN 'breakout' THEN 0 WHEN 'accelerating' THEN 1
                       WHEN 'simmering' THEN 2 WHEN 'fading' THEN 3 ELSE 4 END,
                     COALESCE((ms.inputs->>'P')::float, 0) DESC,
                     (lc.card IS NOT NULL) DESC,   -- cold-start: surface understood entities
                     e.created_at DESC,            -- then newest first, so the sweep is visible
                     e.id
            LIMIT :limit
            """
            ),
            {
                "as_of": as_of,
                "as_of_day": as_of.date(),
                "limit": limit,
                **({"theme": theme} if theme else {}),
                **({"state": state} if state else {}),
                # Dashboard pill 'hn' → the `web` registry (HN-native launches like Kimi).
                **({"source_reg": "web" if source == "hn" else source} if source else {}),
            },
        )
        .mappings()
        .all()
    )

    # Global per-origin entity counts (whole visible universe, independent of the current filters)
    # so the dashboard's source pills show true totals. Counted by anchor registry to match the
    # by-origin filter above; the 'hn' bucket is the HN-native `web` launches.
    counts_row = session.execute(
        text(
            """
            SELECT
              COUNT(*) FILTER (WHERE e.attrs->'anchors' ? 'github') AS github,
              COUNT(*) FILTER (WHERE e.attrs->'anchors' ? 'arxiv')  AS arxiv,
              COUNT(*) FILTER (WHERE e.attrs->'anchors' ? 'hf')     AS hf,
              COUNT(*) FILTER (WHERE e.attrs->'anchors' ? 'web')    AS hn
            FROM entities e
            WHERE e.merged_into IS NULL AND e.tracking_tier <> 'archived'
            """
        )
    ).mappings().one()
    source_counts = {k: int(counts_row[k]) for k in ("github", "arxiv", "hf", "hn")}
    gated_count = session.execute(
        text(
            """
            SELECT COUNT(DISTINCT g.entity_id) FROM gate_decisions g
            JOIN entities e ON e.id = g.entity_id
            WHERE g.decision = 'pass' AND g.week <= :as_of_day
              AND e.merged_into IS NULL AND e.tracking_tier <> 'archived'
            """
        ),
        {"as_of_day": as_of.date()},
    ).scalar_one()

    spark = _sparklines(session, [r["id"] for r in rows], as_of)
    entities = []
    for r in rows:
        inputs = r["inputs"] or {}
        card = r["card"] or {}
        entities.append(
            m.RadarEntity(
                id=r["id"],
                name=r["canonical_name"],
                entity_type=r["entity_type"],
                category=r["category"],
                state=r["state"],
                velocity_pctl=inputs.get("P"),
                maturity_stage=card.get("maturity_stage"),
                one_liner=card.get("what_it_is"),
                provisional=bool(inputs.get("provisional", False)),
                sparkline=spark.get(r["id"], []),
                sources=list(r["sources"] or []),
                gated=bool(r["gated"]),
            )
        )
    return m.RadarResponse(
        as_of=as_of,
        count=len(entities),
        entities=entities,
        source_counts=source_counts,
        gated_count=int(gated_count),
    )


def _sparklines(session: Session, ids: list[int], as_of: datetime) -> dict[int, list[float]]:
    if not ids:
        return {}
    since = as_of.date() - timedelta(days=30)
    rows = session.execute(
        text(
            """
            SELECT entity_id, value FROM entity_metrics_daily
            WHERE metric = :metric AND entity_id = ANY(:ids)
              AND day > :since AND day <= :as_of_day
            ORDER BY entity_id, day
            """
        ),
        {"metric": _HEADLINE_METRIC, "ids": ids, "since": since, "as_of_day": as_of.date()},
    ).all()
    out: dict[int, list[float]] = {}
    for entity_id, value in rows:
        out.setdefault(entity_id, []).append(float(value))
    return out


# --- dossier ----------------------------------------------------------------


@app.get("/entities/{entity_id}", response_model=m.EntityDossier)
def dossier(
    entity_id: int,
    session: Session = Depends(get_session),
    as_of: datetime = Depends(get_as_of),
) -> m.EntityDossier:
    canonical = canonical_entity_id(session, entity_id, as_of)
    ent = (
        session.execute(
            text(
                "SELECT entity_type, canonical_name, attrs, tracking_tier"
                " FROM entities WHERE id = :id"
            ),
            {"id": canonical},
        )
        .mappings()
        .first()
    )
    if ent is None:
        raise HTTPException(status_code=404, detail="entity not found")
    attrs = ent["attrs"] or {}

    first_seen = session.execute(
        text(
            "SELECT MIN(r.occurred_at) FROM entity_links l"
            " JOIN raw_events r ON r.id = l.raw_event_id"
            " WHERE l.entity_id = :id AND l.rule = 'attach' AND r.occurred_at <= :as_of"
        ),
        {"id": canonical, "as_of": as_of},
    ).scalar()

    latest_state = (
        session.execute(
            text(
                "SELECT state, score, inputs FROM momentum_states"
                " WHERE entity_id = :id AND day <= :d"
                " ORDER BY day DESC LIMIT 1"
            ),
            {"id": canonical, "d": as_of.date()},
        )
        .mappings()
        .first()
    )
    inputs = (latest_state["inputs"] if latest_state else {}) or {}

    history = [
        m.MomentumPoint(day=row["day"], state=row["state"], score=_f(row["score"]))
        for row in session.execute(
            text(
                "SELECT day, state, score FROM momentum_states WHERE entity_id = :id"
                " AND day <= :d ORDER BY day DESC LIMIT 60"
            ),
            {"id": canonical, "d": as_of.date()},
        ).mappings()
    ][::-1]

    maturity = [
        m.MaturityRung(stage=row["stage"], promoted_at=row["promoted_at"])
        for row in session.execute(
            text(
                "SELECT stage, promoted_at FROM maturity_promotions WHERE entity_id = :id"
                " AND promoted_at <= :as_of ORDER BY promoted_at"
            ),
            {"id": canonical, "as_of": as_of},
        ).mappings()
    ]

    metrics = _metric_series(session, canonical, as_of)
    card, versions = _card(session, canonical, as_of)
    evidence = _evidence(session, canonical, as_of)
    themes = [
        r[0]
        for r in session.execute(
            text(
                "SELECT DISTINCT th.name FROM entity_themes et"
                " JOIN themes th ON th.id = et.theme_id WHERE et.entity_id = :id ORDER BY th.name"
            ),
            {"id": canonical},
        ).all()
    ]

    description = (attrs.get("text") or "").strip() or None
    if description:
        description = description[:2000]

    return m.EntityDossier(
        id=canonical,
        name=ent["canonical_name"],
        entity_type=ent["entity_type"],
        category=category_asof(session, canonical, as_of),
        anchors=attrs.get("anchors") or {},
        owner=attrs.get("owner"),
        first_seen=(first_seen.date() if first_seen else as_of.date()),
        tracking_tier=ent["tracking_tier"],
        state=(latest_state["state"] if latest_state else "dormant"),
        velocity_pctl=inputs.get("P"),
        provisional=bool(inputs.get("provisional", False)),
        cohort_n=inputs.get("cohort_n"),
        description=description,
        themes=themes,
        maturity=maturity,
        metrics=metrics,
        momentum_history=history,
        evidence=evidence,
        related=_related(session, canonical),
        card=card,
        card_versions=versions,
    )


def _evidence(session: Session, canonical: int, as_of: datetime) -> list[m.EvidenceItem]:
    """The readable sources behind an entity: the discovery/enrichment events (not metric
    snapshots), projected into openable links + text so the dossier can show 'where this came
    from' and 'what it says'."""
    rows = session.execute(
        text(
            """
            SELECT r.source, r.event_type, r.occurred_at, r.payload
            FROM entity_links l JOIN raw_events r ON r.id = l.raw_event_id
            WHERE l.entity_id = :id AND l.rule = 'attach' AND r.occurred_at <= :as_of
              AND r.event_type NOT LIKE '%snapshot%'
            ORDER BY r.occurred_at DESC
            LIMIT 40
            """
        ),
        {"id": canonical, "as_of": as_of},
    ).mappings()

    items: list[m.EvidenceItem] = []
    seen: set[tuple[str | None, str | None]] = set()
    for r in rows:
        item = _evidence_item(r["source"], r["event_type"], r["occurred_at"], r["payload"] or {})
        key = (item.url, item.title)
        if key in seen:
            continue
        seen.add(key)
        items.append(item)
    return items[:20]


def _evidence_item(source: str, event_type: str, occurred_at: datetime, p: dict) -> m.EvidenceItem:
    def _int(x: Any) -> int | None:
        try:
            return int(x) if x is not None else None
        except (TypeError, ValueError):
            return None

    kind, title, url, txt, score, unit = source, None, None, None, None, None
    if event_type == "hn_discussion":
        kind, title, url, txt = "HN discussion", "Community discussion", p.get("url"), p.get("text")
    elif event_type == "launch_page":
        kind, url, title, txt = "Launch page", p.get("url"), p.get("name"), p.get("text")
    elif source == "hn":
        kind, title, url = "Hacker News", p.get("title"), p.get("url")
        score, unit = _int(p.get("points")), "points"
    elif source == "github":
        fn = p.get("full_name") or p.get("repo")
        kind = "README" if event_type == "repo_readme" else "GitHub"
        title = fn
        url = f"https://github.com/{fn}" if fn else (p.get("homepage") or None)
        txt = p.get("text") or p.get("description")
    elif event_type == "model_readme":
        mid = p.get("id")
        kind, title = "Model card", mid
        url = f"https://huggingface.co/{mid}" if mid else None
        txt = p.get("text")
    elif source == "arxiv":
        aid = p.get("arxiv_id")
        kind, title = "arXiv paper", p.get("title")
        url = f"https://arxiv.org/abs/{aid}" if aid else None
        txt = p.get("summary")
    elif source == "hf":
        mid = p.get("id") or p.get("modelId")
        kind, title = "Hugging Face", mid
        url = f"https://huggingface.co/{mid}" if mid else None
        score, unit, txt = _int(p.get("downloads")), "downloads", p.get("description")
    elif source == "openrouter":
        mid = p.get("model_id")
        kind = "OpenRouter rankings" if event_type == "or_rankings" else "OpenRouter listing"
        title = p.get("name") or mid
        url = f"https://openrouter.ai/{mid}" if mid else None
        score, unit = _int(p.get("tokens")), "tokens/wk"
    elif source == "seed":
        kind, title = "Seed", p.get("name")
    return m.EvidenceItem(
        source=source,
        kind=kind,
        title=title,
        url=url,
        text=(str(txt)[:1500] if txt else None),
        score=score,
        unit=unit,
        occurred_at=occurred_at,
    )


def _metric_series(session: Session, canonical: int, as_of: datetime) -> list[m.MetricSeries]:
    since = as_of.date() - timedelta(days=90)
    rows = session.execute(
        text(
            "SELECT metric, day, value FROM entity_metrics_daily WHERE entity_id = :id"
            " AND day > :since AND day <= :d ORDER BY metric, day"
        ),
        {"id": canonical, "since": since, "d": as_of.date()},
    ).all()
    by_metric: dict[str, list[m.SparkPoint]] = {}
    for metric, day, value in rows:
        by_metric.setdefault(metric, []).append(m.SparkPoint(day=day, value=float(value)))
    return [m.MetricSeries(metric=k, points=v) for k, v in sorted(by_metric.items())]


def _related(session: Session, canonical: int) -> list[m.RelatedEntity]:
    """`entity_semantic_edges` neighbors in either direction — a model's judgement, never a rule's
    (see GRAPH_PLAN.md consumer #1). Highest confidence first."""
    rows = (
        session.execute(
            text(
                """
                SELECT dst_label AS label, dst_entity_id AS eid, relation, confidence_score
                FROM entity_semantic_edges WHERE src_entity_id = :id
                UNION ALL
                SELECT src_label AS label, src_entity_id AS eid, relation, confidence_score
                FROM entity_semantic_edges WHERE dst_entity_id = :id
                ORDER BY confidence_score DESC
                """
            ),
            {"id": canonical},
        )
        .mappings()
        .all()
    )
    eids = [r["eid"] for r in rows if r["eid"] is not None]
    categories: dict[int, str | None] = {}
    if eids:
        # Live category, not category_asof: entity_semantic_edges is itself a frozen one-time
        # snapshot with no as_of dimension (GRAPH_PLAN.md) — as-of-scoping just this join would
        # be false precision on top of data that isn't versioned in the first place.
        categories = dict(
            session.execute(
                text("SELECT id, category FROM entities WHERE id = ANY(:ids)"), {"ids": eids}
            ).all()
        )
    return [
        m.RelatedEntity(
            label=r["label"],
            entity_id=r["eid"],
            category=categories.get(r["eid"]) if r["eid"] is not None else None,
            relation=r["relation"],
            confidence_score=float(r["confidence_score"]),
        )
        for r in rows
    ]


def _card(session: Session, canonical: int, as_of: datetime) -> tuple[m.Card | None, list[int]]:
    rows = (
        session.execute(
            text(
                "SELECT version, as_of, status, model, card FROM comprehension_cards"
                " WHERE entity_id = :id AND as_of <= :as_of ORDER BY version DESC"
            ),
            {"id": canonical, "as_of": as_of},
        )
        .mappings()
        .all()
    )
    if not rows:
        return None, []
    versions = [r["version"] for r in rows]
    top = rows[0]
    body = top["card"] or {}
    card = m.Card(
        version=top["version"],
        as_of=top["as_of"],
        status=top["status"],
        model=top["model"],
        what_it_is=body.get("what_it_is"),
        function=body.get("function"),
        claimed_advantage=body.get("claimed_advantage"),
        replaces_or_enables=body.get("replaces_or_enables") or [],
        maturity_stage=body.get("maturity_stage"),
        who_is_behind=body.get("who_is_behind"),
        open_questions=body.get("open_questions") or [],
        confidence=body.get("confidence"),
        category=body.get("category"),
        category_disputed=bool(body.get("category_disputed", False)),
    )
    return card, versions


# --- merge queue (curation) -------------------------------------------------


@app.get("/queue", response_model=list[m.QueueItem])
def queue(
    session: Session = Depends(get_session), limit: int = Query(50, le=200)
) -> list[m.QueueItem]:
    rows = (
        session.execute(
            text(
                """
            SELECT q.id, q.confidence, q.evidence, q.status,
                   a.id AS a_id, a.canonical_name AS a_name, a.entity_type AS a_type,
                   a.category AS a_cat, a.attrs->>'owner' AS a_owner,
                   b.id AS b_id, b.canonical_name AS b_name, b.entity_type AS b_type,
                   b.category AS b_cat, b.attrs->>'owner' AS b_owner
            FROM entity_merge_queue q
            JOIN entities a ON a.id = q.entity_a
            JOIN entities b ON b.id = q.entity_b
            WHERE q.status IN ('pending', 'deferred_coldstart')
            ORDER BY q.confidence DESC, q.id
            LIMIT :limit
            """
            ),
            {"limit": limit},
        )
        .mappings()
        .all()
    )
    return [
        m.QueueItem(
            id=r["id"],
            confidence=r["confidence"],
            evidence=r["evidence"] or {},
            status=r["status"],
            entity_a=m.MiniEntity(
                id=r["a_id"],
                name=r["a_name"],
                entity_type=r["a_type"],
                category=r["a_cat"],
                owner=r["a_owner"],
            ),
            entity_b=m.MiniEntity(
                id=r["b_id"],
                name=r["b_name"],
                entity_type=r["b_type"],
                category=r["b_cat"],
                owner=r["b_owner"],
            ),
        )
        for r in rows
    ]


@app.post(
    "/merge-queue/{queue_id}/decision",
    response_model=m.DecisionResult,
    dependencies=[Depends(require_token)],
)
def decide(
    queue_id: int,
    decision: str = Query(..., pattern="^(merge|reject|skip)$"),
    session: Session = Depends(get_session),
    as_of: datetime = Depends(get_as_of),
) -> m.DecisionResult:
    row = (
        session.execute(
            text(
                "SELECT entity_a, entity_b, confidence, evidence"
                " FROM entity_merge_queue WHERE id = :id"
            ),
            {"id": queue_id},
        )
        .mappings()
        .first()
    )
    if row is None:
        raise HTTPException(status_code=404, detail="queue item not found")

    status_map = {"reject": "rejected", "skip": "skipped", "merge": "merged"}
    merged = False
    if decision == "merge":
        _apply_merge(session, row, as_of)
        merged = True
    session.execute(
        text("UPDATE entity_merge_queue SET status = :s, decided_at = now() WHERE id = :id"),
        {"s": status_map[decision], "id": queue_id},
    )
    return m.DecisionResult(id=queue_id, status=status_map[decision], merged=merged)


def _apply_merge(session: Session, row: Any, as_of: datetime) -> None:
    """Human-approved merge: survivor = earliest-created entity; append an ``entity_merges`` row
    (reversible, decided_by='human') and set the ``merged_into`` denorm."""
    a, b = row["entity_a"], row["entity_b"]
    order = (
        session.execute(
            text("SELECT id FROM entities WHERE id IN (:a, :b) ORDER BY created_at, id"),
            {"a": a, "b": b},
        )
        .scalars()
        .all()
    )
    survivor, loser = order[0], order[1]
    session.execute(
        text(
            "INSERT INTO entity_merges (loser_id, survivor_id, justified_at, rule, confidence,"
            " decided_by, active) VALUES (:l, :s, :j, 'human', :c, 'human', true)"
            " ON CONFLICT (loser_id) DO NOTHING"
        ),
        {"l": loser, "s": survivor, "j": as_of, "c": row["confidence"]},
    )
    session.execute(
        text("UPDATE entities SET merged_into = :s WHERE id = :l"), {"s": survivor, "l": loser}
    )


# --- significance gate audit (doc 07 §3) ------------------------------------


def _iso_week(d: date) -> str:
    iso = d.isocalendar()
    return f"{iso.year}-W{iso.week:02d}"


@app.get("/gate/{week}", response_model=m.GateWeekResponse)
def gate_week(week: str, session: Session = Depends(get_session)) -> m.GateWeekResponse:
    """A week's gate decisions — passed + suppressed with the M×R×N breakdown and map-gaps.

    ``week`` is an ISO week (``2026-W28``) or ``current``/``latest`` (the most recent week that has
    decisions, else the current calendar week). Trust in the gate comes from seeing what it did
    *not* pass, so the suppressed list — with reasons — is first-class here (doc 07 §3)."""
    from seismo.significance.gate import parse_week

    if week in ("current", "latest"):
        latest = session.execute(text("SELECT MAX(week) FROM gate_decisions")).scalar()
        week_start = latest or parse_week(None)
    else:
        try:
            week_start = parse_week(week)
        except (ValueError, IndexError) as exc:
            raise HTTPException(status_code=400, detail=f"bad week {week!r}") from exc

    rows = (
        session.execute(
            text(
                """
                SELECT g.entity_id, g.decision, g.score, g.components,
                       e.canonical_name, e.entity_type, e.category
                FROM gate_decisions g
                JOIN entities e ON e.id = g.entity_id
                WHERE g.week = :w
                ORDER BY g.score DESC, g.entity_id
                """
            ),
            {"w": week_start},
        )
        .mappings()
        .all()
    )

    passed: list[m.GateDecisionItem] = []
    suppressed: list[m.GateDecisionItem] = []
    map_gaps: dict[str, int] = {}
    for r in rows:
        comps = r["components"] or {}
        item = m.GateDecisionItem(
            entity_id=r["entity_id"],
            name=r["canonical_name"],
            entity_type=r["entity_type"],
            category=r["category"],
            decision=r["decision"],
            score=_f(r["score"]) or 0.0,
            components=m.GateComponents(**{k: comps.get(k) for k in m.GateComponents.model_fields}),
        )
        if r["decision"] == "pass":
            passed.append(item)
        else:
            suppressed.append(item)
            if comps.get("reason") == "unmapped_reach" and r["category"]:
                map_gaps[r["category"]] = map_gaps.get(r["category"], 0) + 1

    weeks = [
        _iso_week(w)
        for w in session.execute(
            text("SELECT DISTINCT week FROM gate_decisions ORDER BY week DESC")
        ).scalars()
    ]
    return m.GateWeekResponse(
        week=week_start,
        briefs_budget=settings.briefs_per_week,
        passed=passed,
        suppressed=suppressed,
        map_gaps=dict(sorted(map_gaps.items(), key=lambda x: -x[1])),
        available_weeks=weeks,
    )


# --- impact briefs (doc 08 §4 — review workflow) ----------------------------


@app.get("/briefs", response_model=list[m.BriefListItem])
def briefs(
    session: Session = Depends(get_session),
    status: str | None = Query(None, description="Filter by status; default draft+published."),
    limit: int = Query(50, le=200),
) -> list[m.BriefListItem]:
    """The review inbox (doc 08 §4): the latest brief version per entity, newest first. Defaults to
    the actionable set (draft awaiting review + already published); pass ``status`` to narrow."""
    statuses = [status] if status else ["draft", "published"]
    rows = (
        session.execute(
            text(
                """
                WITH latest AS (
                    SELECT DISTINCT ON (entity_id) id, entity_id, version, status, as_of,
                           created_at, brief
                    FROM impact_briefs
                    ORDER BY entity_id, version DESC
                )
                SELECT l.*, e.canonical_name
                FROM latest l JOIN entities e ON e.id = l.entity_id
                WHERE l.status = ANY(:statuses)
                ORDER BY l.created_at DESC
                LIMIT :limit
                """
            ),
            {"statuses": statuses, "limit": limit},
        )
        .mappings()
        .all()
    )
    out = []
    for r in rows:
        body = r["brief"] or {}
        out.append(
            m.BriefListItem(
                id=r["id"],
                entity_id=r["entity_id"],
                entity_name=r["canonical_name"],
                version=r["version"],
                status=r["status"],
                as_of=r["as_of"],
                created_at=r["created_at"],
                mechanisms=body.get("mechanisms") or [],
                n_exposures=len(body.get("exposures") or []),
                summary=body.get("summary"),
            )
        )
    return out


@app.get("/briefs/{entity_id}", response_model=m.Brief)
def brief_detail(
    entity_id: int,
    session: Session = Depends(get_session),
    version: int | None = Query(None, description="A specific version; default the latest."),
) -> m.Brief:
    """One entity's impact brief, rendered for the review page (doc 08 §4)."""
    return _brief_response(session, entity_id, version)


def _brief_response(session: Session, entity_id: int, version: int | None = None) -> m.Brief:
    rows = (
        session.execute(
            text(
                "SELECT id, version, as_of, status, model, reviewed_at, brief "
                "FROM impact_briefs WHERE entity_id = :e ORDER BY version DESC"
            ),
            {"e": entity_id},
        )
        .mappings()
        .all()
    )
    if not rows:
        raise HTTPException(status_code=404, detail="no brief for this entity")
    versions = [r["version"] for r in rows]
    row = rows[0] if version is None else next((r for r in rows if r["version"] == version), None)
    if row is None:
        raise HTTPException(status_code=404, detail=f"brief version {version} not found")

    name = session.execute(
        text("SELECT canonical_name FROM entities WHERE id = :e"), {"e": entity_id}
    ).scalar()
    body = row["brief"] or {}
    council_rows = (
        session.execute(
            text(
                "SELECT role, stance, confidence, reasoning, model FROM council_verdicts "
                "WHERE impact_brief_id = :b ORDER BY role"
            ),
            {"b": row["id"]},
        )
        .mappings()
        .all()
    )
    council = [m.CouncilVerdictItem(**dict(c)) for c in council_rows]
    council_stance = aggregate_stance([c.stance for c in council]) if len(council) == 3 else None
    return m.Brief(
        id=row["id"],
        entity_id=entity_id,
        entity_name=name or str(entity_id),
        version=row["version"],
        as_of=row["as_of"],
        status=row["status"],
        model=row["model"],
        reviewed_at=row["reviewed_at"],
        reject_reason=body.get("_reject_reason"),
        entity_ref=body.get("entity_ref"),
        mechanisms=body.get("mechanisms") or [],
        transmission_path=[
            m.BriefTransmissionStep(**s) for s in (body.get("transmission_path") or [])
        ],
        exposures=[m.BriefExposure(**e) for e in (body.get("exposures") or [])],
        counter_mechanism=body.get("counter_mechanism"),
        observables=[m.BriefObservable(**o) for o in (body.get("observables") or [])],
        confidence=body.get("confidence"),
        horizon=body.get("horizon"),
        summary=body.get("summary"),
        evidence_refs=body.get("evidence_refs") or [],
        versions=versions,
        council=council,
        council_stance=council_stance,
    )


@app.post(
    "/briefs/{entity_id}/council",
    response_model=m.Brief,
    dependencies=[Depends(require_token)],
)
def run_council_now(
    entity_id: int,
    session: Session = Depends(get_session),
) -> m.Brief:
    """Trigger one council review, on demand, for one entity only — the click-triggered path
    (never bulk/batch). Same `run_council(entity_id=...)` the CLI uses, just invoked from the
    dashboard's "Run council review" button instead of a terminal; three LLM calls happen here,
    synchronously, only because a human just asked for exactly this one."""
    from seismo.checkpoints.council import run_council

    stats = run_council(session, datetime.now(UTC), entity_id=entity_id)
    if stats.reviewed == 0:
        raise HTTPException(
            status_code=422, detail="council review failed to produce a brief for this entity"
        )
    return _brief_response(session, entity_id)


@app.post(
    "/briefs/{brief_id}/decision",
    response_model=m.BriefDecisionResult,
    dependencies=[Depends(require_token)],
)
def brief_decision(
    brief_id: int,
    decision: str = Query(..., pattern="^(publish|reject)$"),
    reason: str | None = Query(None, description="Required when rejecting (doc 08 §4)."),
    session: Session = Depends(get_session),
) -> m.BriefDecisionResult:
    """Human review (DR-08.2): publish a draft, or reject it with a reason kept for the quality loop
    (doc 05 §6). Only a ``draft`` can be decided; published briefs are immutable."""
    row = (
        session.execute(
            text("SELECT status, brief FROM impact_briefs WHERE id = :id"), {"id": brief_id}
        )
        .mappings()
        .first()
    )
    if row is None:
        raise HTTPException(status_code=404, detail="brief not found")
    if row["status"] != "draft":
        raise HTTPException(status_code=409, detail=f"brief is {row['status']}, not a draft")
    if decision == "reject" and not reason:
        raise HTTPException(status_code=400, detail="a reject reason is required")

    if decision == "publish":
        session.execute(
            text(
                "UPDATE impact_briefs SET status = 'published', reviewed_at = now() WHERE id = :id"
            ),
            {"id": brief_id},
        )
        return m.BriefDecisionResult(id=brief_id, status="published")

    body = dict(row["brief"] or {})
    body["_reject_reason"] = reason
    session.execute(
        text(
            "UPDATE impact_briefs SET status = 'rejected', reviewed_at = now(), "
            "brief = CAST(:b AS JSONB) WHERE id = :id"
        ),
        {"id": brief_id, "b": _dumps(body)},
    )
    return m.BriefDecisionResult(id=brief_id, status="rejected")


def _dumps(value: dict[str, Any]) -> str:
    import json

    return json.dumps(value)


# --- memory & synthesis (doc 09) --------------------------------------------

# Fixed display order for the Changes view groups (doc 09 §1) — most consequential first.
_CHANGE_ORDER = [
    "gate_week",
    "brief_published",
    "brief_drafted",
    "state_up",
    "state_down",
    "promotion",
    "new_entity",
]


@app.get("/changes/{day}", response_model=m.ChangesResponse)
def changes(day: str, session: Session = Depends(get_session)) -> m.ChangesResponse:
    """One day's deterministic Changes view (doc 09 §1). ``day`` is an ISO date or ``latest`` (the
    most recent day that has computed changes)."""
    if day in ("latest", "current"):
        resolved = session.execute(text("SELECT MAX(day) FROM changes_daily")).scalar()
        target = resolved or datetime.now(UTC).date()
    else:
        try:
            target = date.fromisoformat(day)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=f"bad day {day!r}") from exc

    rows = (
        session.execute(
            text(
                "SELECT kind, entity_id, text, payload FROM changes_daily"
                " WHERE day = :d ORDER BY id"
            ),
            {"d": target},
        )
        .mappings()
        .all()
    )
    # Category as it was on `target`, not today's (invariant 2) — every entity_id only resolved
    # once, since a day's changes can repeat the same entity across kinds.
    day_end = datetime.combine(target, datetime.max.time(), tzinfo=UTC)
    category_of: dict[int, str | None] = {}
    groups: dict[str, list[m.ChangeItem]] = {}
    for r in rows:
        eid = r["entity_id"]
        if eid is not None and eid not in category_of:
            category_of[eid] = category_asof(session, eid, day_end)
        groups.setdefault(r["kind"], []).append(
            m.ChangeItem(
                kind=r["kind"],
                entity_id=eid,
                text=r["text"],
                payload=r["payload"] or {},
                category=category_of.get(eid) if eid is not None else None,
            )
        )
    ordered = {k: groups[k] for k in _CHANGE_ORDER if k in groups}
    for k, v in groups.items():  # any kinds not in the fixed order, appended stably
        if k not in ordered:
            ordered[k] = v

    days = [
        d.isoformat()
        for d in session.execute(
            text("SELECT DISTINCT day FROM changes_daily ORDER BY day DESC LIMIT 30")
        ).scalars()
    ]
    return m.ChangesResponse(day=target, groups=ordered, total=len(rows), available_days=days)


@app.get("/calibration", response_model=m.CalibrationResponse)
def calibration(session: Session = Depends(get_session)) -> m.CalibrationResponse:
    """The momentum-call calibration track record (doc 09 §3), per metric over time."""
    rows = (
        session.execute(
            text(
                "SELECT day, metric, value, sample_n FROM calibration_snapshots "
                "ORDER BY metric, day"
            )
        )
        .mappings()
        .all()
    )
    series: dict[str, list[m.CalibrationPoint]] = {}
    for r in rows:
        series.setdefault(r["metric"], []).append(
            m.CalibrationPoint(day=r["day"], value=_f(r["value"]), sample_n=r["sample_n"])
        )
    latest = {metric: pts[-1] for metric, pts in series.items() if pts}
    return m.CalibrationResponse(series=series, latest=latest)


@app.get("/briefs/{entity_id}/score-packet", response_model=m.ScorePacketResponse)
def score_packet(
    entity_id: int,
    session: Session = Depends(get_session),
    version: int | None = Query(None),
) -> m.ScorePacketResponse:
    """Assemble the quarterly scoring screen for an entity's latest (or a specific) brief version,
    with its system observables auto-evaluated (A-7, doc 09 §2)."""
    from seismo.memory.scoring import assemble_score_packet

    row = session.execute(
        text(
            "SELECT id FROM impact_briefs WHERE entity_id = :e "
            + ("AND version = :v " if version is not None else "")
            + "ORDER BY version DESC LIMIT 1"
        ),
        {"e": entity_id, **({"v": version} if version is not None else {})},
    ).scalar()
    if row is None:
        raise HTTPException(status_code=404, detail="no brief for this entity")

    p = assemble_score_packet(session, int(row))
    existing = None
    if p.existing_score is not None:
        notes = _loads(p.existing_score.get("notes"))
        existing = m.ExistingScore(
            materialized=p.existing_score.get("materialized"),
            falsifier_tripped=p.existing_score.get("falsifier_tripped"),
            verdict=notes.get("verdict"),
            counter_was_better=notes.get("counter_was_better"),
            falsifier_observable=notes.get("falsifier_observable"),
        )
    return m.ScorePacketResponse(
        brief_id=p.brief_id,
        entity_id=p.entity_id,
        entity_name=p.entity_name,
        version=p.version,
        published_at=p.published_at,
        horizon=p.horizon,
        days_elapsed=p.days_elapsed,
        summary=p.summary,
        counter_mechanism=p.counter_mechanism,
        exposures=[m.BriefExposure(**e) for e in p.exposures],
        observable_evals=[
            m.ObservableEvalModel(
                statement=ev.statement,
                source=ev.source,
                system_metric=ev.system_metric,
                direction_if_thesis_holds=ev.direction_if_thesis_holds,
                status=ev.status,
                detail=ev.detail,
            )
            for ev in p.observable_evals
        ],
        metric_history={k: [list(t) for t in v] for k, v in p.metric_history.items()},
        auto_summary=p.auto_summary,
        existing_score=existing,
    )


@app.post(
    "/briefs/{brief_id}/score",
    response_model=m.ScoreResult,
    dependencies=[Depends(require_token)],
)
def score_brief(
    brief_id: int,
    materialized: str = Query(..., pattern="^(yes|partial|no|too_early)$"),
    falsifier_tripped: bool = Query(False),
    falsifier_observable: str | None = Query(None),
    verdict: str | None = Query(None),
    counter_was_better: bool = Query(False),
    session: Session = Depends(get_session),
) -> m.ScoreResult:
    """Record the operator's quarterly forward-score for a brief (DR-09.2 — the human ritual)."""
    from seismo.memory.scoring import record_score

    try:
        record_score(
            session,
            brief_id,
            materialized=materialized,
            falsifier_tripped=falsifier_tripped,
            falsifier_observable=falsifier_observable,
            verdict=verdict,
            counter_was_better=counter_was_better,
        )
    except ValueError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return m.ScoreResult(brief_id=brief_id, materialized=materialized)


def _loads(value: Any) -> dict[str, Any]:
    import json

    if not value:
        return {}
    if isinstance(value, dict):
        return value
    try:
        loaded = json.loads(value)
    except (ValueError, TypeError):
        return {}
    return loaded if isinstance(loaded, dict) else {}


# --- search (A-10) ----------------------------------------------------------


@app.get("/search", response_model=list[m.SearchHit])
def search(
    q: str = Query(..., min_length=1),
    type: str | None = Query(None),
    session: Session = Depends(get_session),
    limit: int = Query(20, le=100),
) -> list[m.SearchHit]:
    """Trigram + prefix search over entity names (doc 13 A-10). Full FTS is a later add."""
    rows = (
        session.execute(
            text(
                """
            SELECT e.id, e.canonical_name, e.entity_type, e.category,
                   (SELECT state FROM momentum_states WHERE entity_id = e.id
                    ORDER BY day DESC LIMIT 1) AS state
            FROM entities e
            WHERE e.merged_into IS NULL
              AND (e.canonical_name ILIKE :like OR e.canonical_name % :q)
              """
                + ("AND e.entity_type = :type " if type else "")
                + """
            ORDER BY similarity(e.canonical_name, :q) DESC, e.canonical_name
            LIMIT :limit
            """
            ),
            {"q": q, "like": f"%{q}%", "limit": limit, **({"type": type} if type else {})},
        )
        .mappings()
        .all()
    )
    return [
        m.SearchHit(
            id=r["id"],
            name=r["canonical_name"],
            entity_type=r["entity_type"],
            category=r["category"],
            state=r["state"],
        )
        for r in rows
    ]


# --- correlation graph (doc 13 — GRAPH_PLAN.md) ------------------------------


def _concept_id(label: str) -> str:
    slug = re.sub(r"[^a-z0-9]+", "-", label.lower()).strip("-")
    return f"c:{slug or 'unknown'}"


@app.get("/graph", response_model=m.GraphResponse)
def graph(session: Session = Depends(get_session)) -> m.GraphResponse:
    """The correlation graph: the deterministic spine (`entity_graph_edges` — built_by/cited/
    depends_on, every row justified by a raw_event) plus the LLM-reasoned relation graph
    (`entity_semantic_edges` — semantically_similar_to/conceptually_related_to). Kept visually
    distinguishable by the caller (`kind` on each edge) since one is provable and the other is a
    model's judgement — never merge the two into one undifferentiated line style."""
    nodes: dict[str, m.GraphNode] = {}
    edges: list[m.GraphEdge] = []

    def entity_id_of(eid: int) -> str:
        return f"e:{eid}"

    det_rows = (
        session.execute(
            text(
                """
                SELECT ge.src_entity_id, ge.dst_entity_id, ge.edge_type, ge.weight,
                       e1.canonical_name AS src_name, e1.category AS src_cat,
                       e2.canonical_name AS dst_name, e2.category AS dst_cat
                FROM entity_graph_edges ge
                JOIN entities e1 ON e1.id = ge.src_entity_id
                JOIN entities e2 ON e2.id = ge.dst_entity_id
                """
            )
        )
        .mappings()
        .all()
    )
    for r in det_rows:
        sid, did = entity_id_of(r["src_entity_id"]), entity_id_of(r["dst_entity_id"])
        nodes.setdefault(
            sid,
            m.GraphNode(
                id=sid, label=r["src_name"], kind="entity",
                category=r["src_cat"], entity_id=r["src_entity_id"],
            ),
        )
        nodes.setdefault(
            did,
            m.GraphNode(
                id=did, label=r["dst_name"], kind="entity",
                category=r["dst_cat"], entity_id=r["dst_entity_id"],
            ),
        )
        edges.append(
            m.GraphEdge(
                source=sid, target=did, relation=r["edge_type"],
                kind="deterministic", weight=float(r["weight"]),
            )
        )

    sem_rows = (
        session.execute(
            text(
                """
                SELECT se.src_entity_id, se.dst_entity_id, se.src_label, se.dst_label,
                       se.relation, se.confidence_score,
                       e1.category AS src_cat, e2.category AS dst_cat
                FROM entity_semantic_edges se
                LEFT JOIN entities e1 ON e1.id = se.src_entity_id
                LEFT JOIN entities e2 ON e2.id = se.dst_entity_id
                """
            )
        )
        .mappings()
        .all()
    )
    for r in sem_rows:
        src_eid, dst_eid = r["src_entity_id"], r["dst_entity_id"]
        sid = entity_id_of(src_eid) if src_eid is not None else _concept_id(r["src_label"])
        did = entity_id_of(dst_eid) if dst_eid is not None else _concept_id(r["dst_label"])
        nodes.setdefault(
            sid,
            m.GraphNode(
                id=sid, label=r["src_label"], kind="entity" if src_eid is not None else "concept",
                category=r["src_cat"], entity_id=src_eid,
            ),
        )
        nodes.setdefault(
            did,
            m.GraphNode(
                id=did, label=r["dst_label"], kind="entity" if dst_eid is not None else "concept",
                category=r["dst_cat"], entity_id=dst_eid,
            ),
        )
        edges.append(
            m.GraphEdge(
                source=sid, target=did, relation=r["relation"],
                kind="reasoned", weight=float(r["confidence_score"]),
            )
        )

    return m.GraphResponse(nodes=list(nodes.values()), edges=edges)


def _f(value: Any) -> float | None:
    return None if value is None else float(value)
