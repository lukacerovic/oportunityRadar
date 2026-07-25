"""Continuous discovery triage (Feature 6) — the ``seismo triage`` step.

``resolve`` mints an ``entities`` row for *every* unlinked discovery event unconditionally (cheap,
and useful to the identity graph). Triage is the separate, later gate: for each freshly-minted,
still-``active`` discovery entity it decides — track or archive — and flips ``tracking_tier`` to
``archived`` for the ones that don't clear the bar, reusing Seismograph's existing A-4 bounded-
tracking mechanism rather than gating creation in ``resolve``. An untriaged entity gets at most one
day of tracking before this catches it — acceptable and self-correcting.

Pure orchestration, DB-only, **no network**: the triage "facts" are read straight out of the
already-collected metric/attr state. The one optional escalation is :func:`complete_triage` (the
sole LLM entry point), which is fail-closed — ``None`` for the ``mock`` provider or any CLI failure
— in which case a deterministic stars/downloads threshold decides instead.

Idempotent by construction: a candidate is an ``active``, unmerged entity with *no* existing
``discovery_triage_decisions`` row (guarded further by that table's ``entity_id UNIQUE``), so a
re-run naturally skips everything already decided.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from seismo.checkpoints.llm import complete_triage
from seismo.config import settings

_DESCRIPTION_CAP = 300  # chars of descriptive text handed to triage as a "facts" field

# Non-discovery entity types: ``person`` (GitHub contributors) and ``paper`` (README citations) are
# minted by the graph-edges derivation pass, not by discovery, so they are never triage candidates.
_EXCLUDED_TYPES = ("person", "paper")

# The metric names read from ``entity_metrics_daily`` to build a candidate's facts (latest value).
_METRIC_STARS = "gh_stars"
_METRIC_HF = "hf_downloads_30d"
_METRIC_PYPI = "pypi_downloads_7d"


@dataclass
class TriageStats:
    candidates: int = 0
    tracked: int = 0
    skipped: int = 0
    by_ai: int = 0
    by_threshold: int = 0
    deferred: int = 0  # no metrics row yet — left un-decided, not archived on zero information

    def as_note(self) -> str:
        return (
            f"{self.candidates} candidates → track={self.tracked} skip={self.skipped} "
            f"deferred={self.deferred} (ai={self.by_ai} threshold={self.by_threshold})"
        )


@dataclass
class _Candidate:
    id: int
    entity_type: str
    canonical_name: str
    category: str | None
    created_at: datetime
    attrs: dict[str, Any]

    @property
    def registries(self) -> list[str]:
        anchors = self.attrs.get("anchors")
        return sorted(anchors) if isinstance(anchors, dict) else []


def run_triage(
    session: Session, *, limit: int | None = None, dry_run: bool = False
) -> TriageStats:
    """Triage every un-decided, active, unmerged discovery entity. Caller commits.

    ``limit`` caps the batch (cost/rate budget); ``dry_run`` computes the same stats but writes no
    rows and makes no ``tracking_tier`` change. An entity with no ``entity_metrics_daily`` row at
    all that also gets no AI decision is deferred rather than threshold-archived on zero
    information: the module's own contract is "at most one day of tracking before this catches
    it," which only holds if `track`/`snapshot` ran first — deferring keeps that true regardless
    of run order, instead of silently archiving a same-day discovery with no re-entry path (a
    candidate is only ever un-decided once). The AI path still gets a chance first since it can
    reason from qualitative facts (name/description) alone, without metrics."""
    now = datetime.now(UTC)
    candidates = _load_candidates(session, limit)
    metrics = _load_latest_metrics(session, [c.id for c in candidates])
    stats = TriageStats(candidates=len(candidates))

    for cand in candidates:
        m = metrics.get(cand.id, {})
        stars = _as_int(m.get(_METRIC_STARS))
        hf_downloads = _as_int(m.get(_METRIC_HF))
        pypi_downloads = _as_int(m.get(_METRIC_PYPI))
        registries = cand.registries
        # ``downloads`` fact: the usage level that applies to this entity — HF's rolling 30d if it
        # carries an HF anchor, else PyPI's rolling 7d.
        downloads = hf_downloads if "hf" in registries else pypi_downloads
        facts = _build_facts(cand, registries, stars, downloads, now)

        result = complete_triage(facts)
        if isinstance(result, dict) and result.get("decision") in ("track", "skip"):
            decision = str(result["decision"])
            decided_by = "ai"
            model = f"claude_cli:{settings.claude_cli_model}"
            sector = result.get("sector")
        elif cand.id not in metrics:
            # No AI decision AND no metrics at all — the deterministic threshold would only ever
            # say "skip" from all-None inputs. Defer instead of archiving on zero information.
            stats.deferred += 1
            continue
        else:
            # Fail-closed fallback (mock provider, or the CLI failed): deterministic threshold.
            decision = (
                "track"
                if _threshold_track(
                    cand.entity_type, registries, stars, hf_downloads, pypi_downloads
                )
                else "skip"
            )
            decided_by = "threshold"
            model = None
            sector = None

        if decision == "track":
            stats.tracked += 1
        else:
            stats.skipped += 1
        if decided_by == "ai":
            stats.by_ai += 1
        else:
            stats.by_threshold += 1

        if not dry_run:
            _record(session, cand, decision, sector, decided_by, model, facts)

    return stats


# --- candidate + facts ------------------------------------------------------


def _load_candidates(session: Session, limit: int | None) -> list[_Candidate]:
    """Active, unmerged entities with no triage decision yet, excluding graph-derived types and the
    hand-curated seed universe (flagged by ``attrs['seed_category']``). Ordered by id for a stable,
    resumable batch order."""
    sql = text(
        """
        SELECT e.id, e.entity_type, e.canonical_name, e.category, e.created_at, e.attrs
        FROM entities e
        WHERE e.merged_into IS NULL
          AND e.tracking_tier = 'active'
          AND e.entity_type <> ALL(:excluded)
          AND NOT (e.attrs ? 'seed_category')
          AND NOT EXISTS (
            SELECT 1 FROM discovery_triage_decisions d WHERE d.entity_id = e.id
          )
        ORDER BY e.id
        """
        + ("LIMIT :limit" if limit is not None else "")
    )
    params: dict[str, object] = {"excluded": list(_EXCLUDED_TYPES)}
    if limit is not None:
        params["limit"] = limit
    return [
        _Candidate(
            id=row.id,
            entity_type=row.entity_type,
            canonical_name=row.canonical_name,
            category=row.category,
            created_at=row.created_at,
            attrs=dict(row.attrs or {}),
        )
        for row in session.execute(sql, params)
    ]


def _load_latest_metrics(
    session: Session, entity_ids: list[int]
) -> dict[int, dict[str, Any]]:
    """``{entity_id -> {metric -> latest value}}`` for the triage metrics, using the newest day's
    value per (entity, metric). One query for the whole batch."""
    if not entity_ids:
        return {}
    rows = session.execute(
        text(
            """
            SELECT DISTINCT ON (entity_id, metric) entity_id, metric, value
            FROM entity_metrics_daily
            WHERE entity_id = ANY(:ids) AND metric = ANY(:metrics)
            ORDER BY entity_id, metric, day DESC
            """
        ),
        {"ids": entity_ids, "metrics": [_METRIC_STARS, _METRIC_HF, _METRIC_PYPI]},
    )
    out: dict[int, dict[str, Any]] = {}
    for row in rows:
        out.setdefault(row.entity_id, {})[row.metric] = row.value
    return out


def _build_facts(
    cand: _Candidate,
    registries: list[str],
    stars: int | None,
    downloads: int | None,
    now: datetime,
) -> dict[str, Any]:
    text_attr = cand.attrs.get("text")
    description = (
        str(text_attr).strip()[:_DESCRIPTION_CAP]
        if isinstance(text_attr, str) and text_attr
        else None
    )
    return {
        "name": cand.canonical_name,
        "entity_type": cand.entity_type,
        "category": cand.category,
        "registries": registries,
        "stars": stars,
        "downloads": downloads,
        "age_days": max((now - cand.created_at).days, 0),
        "description": description,
    }


# --- decisions --------------------------------------------------------------


def _threshold_track(
    entity_type: str,
    registries: list[str],
    stars: int | None,
    hf_downloads: int | None,
    pypi_downloads: int | None,
) -> bool:
    """Deterministic fallback bar when the LLM is unavailable: track iff a github repo cleared the
    star threshold, an HF model cleared the downloads threshold, or a PyPI package cleared its own
    downloads threshold. A ``paper`` (arxiv-only) is never threshold-tracked."""
    if entity_type == "paper":
        return False
    by_stars = (
        "github" in registries
        and stars is not None
        and stars >= settings.triage_github_star_threshold
    )
    by_hf_downloads = (
        "hf" in registries
        and hf_downloads is not None
        and hf_downloads >= settings.triage_hf_downloads_threshold
    )
    by_pypi_downloads = (
        "pypi" in registries
        and pypi_downloads is not None
        and pypi_downloads >= settings.triage_pypi_downloads_threshold
    )
    return by_stars or by_hf_downloads or by_pypi_downloads


def _record(
    session: Session,
    cand: _Candidate,
    decision: str,
    sector: str | None,
    decided_by: str,
    model: str | None,
    facts: dict[str, Any],
) -> None:
    """Write the decision row and apply its effect: the ``tracking_tier`` flip plus the ``triage``
    (and, for tracked entities, ``discovered_by``) breadcrumbs on ``attrs``. Idempotent — the
    candidate query already excludes decided entities, and ``entity_id UNIQUE`` is the backstop."""
    session.execute(
        text(
            """
            INSERT INTO discovery_triage_decisions
              (entity_id, decision, sector, decided_by, model, facts)
            VALUES (:e, :dec, :sec, :by, :model, CAST(:facts AS JSONB))
            ON CONFLICT (entity_id) DO NOTHING
            """
        ),
        {
            "e": cand.id,
            "dec": decision,
            "sec": sector,
            "by": decided_by,
            "model": model,
            "facts": json.dumps(facts, default=str),
        },
    )
    attrs = dict(cand.attrs)
    attrs["triage"] = {"decision": decision, "sector": sector, "decided_by": decided_by}
    tier = "active" if decision == "track" else "archived"
    if decision == "track":
        attrs["discovered_by"] = f"discovery+{decided_by}"
    session.execute(
        text(
            "UPDATE entities SET tracking_tier = :tier, attrs = CAST(:a AS JSONB) WHERE id = :id"
        ),
        {"tier": tier, "a": json.dumps(attrs, default=str), "id": cand.id},
    )


def _as_int(value: Any) -> int | None:
    if value is None:
        return None
    return int(value)
