"""FastAPI read + curation API (doc 10 §1) — the *only* door to the knowledge graph.

The dashboard never touches Postgres; every projection goes through here, which keeps the ``as_of``
discipline in one place (all read endpoints accept ``as_of`` for time-travel). Reads are open;
curation (non-GET) requires the static bearer token (DR-10.2). Pydantic models everywhere so the
OpenAPI schema generates a drift-proof TS client.
"""

from __future__ import annotations

from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

from fastapi import Depends, FastAPI, Header, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from sqlalchemy import text
from sqlalchemy.orm import Session

from seismo.api import models as m
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
            )
            SELECT e.id, e.canonical_name, e.entity_type, e.category,
                   COALESCE(ms.state, 'dormant') AS state, ms.inputs, lc.card
            FROM entities e
            LEFT JOIN ms ON ms.entity_id = e.id
            LEFT JOIN lc ON lc.entity_id = e.id
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
            },
        )
        .mappings()
        .all()
    )

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
            )
        )
    return m.RadarResponse(as_of=as_of, count=len(entities), entities=entities)


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
        maturity=maturity,
        metrics=metrics,
        momentum_history=history,
        card=card,
        card_versions=versions,
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


def _f(value: Any) -> float | None:
    return None if value is None else float(value)
