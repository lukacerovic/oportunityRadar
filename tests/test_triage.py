"""Feature 6 — continuous discovery triage (``seismo triage`` / :func:`run_triage`).

Runs on ``clean_db``. Two provider paths are exercised without any subprocess:

* the deterministic threshold path — ``settings.llm_provider="mock"`` forces ``complete_triage`` →
  ``None``, so a stars/downloads bar decides;
* the "ai" path — ``complete_triage`` is monkeypatched to a stub, so we assert provenance
  (``decided_by='ai'``, ``model`` populated, ``sector`` stored) without an LLM.

Plus idempotency, dry-run, candidate exclusions, and the pure threshold helper.
"""

from __future__ import annotations

import itertools
import json
from datetime import UTC, datetime

from sqlalchemy import text
from sqlalchemy.orm import Session

from seismo.config import settings
from seismo.identity import triage as triage_mod
from seismo.identity.triage import _threshold_track, run_triage

_UID = itertools.count(1)


# --- helpers ----------------------------------------------------------------


def _entity(
    session: Session,
    name: str,
    *,
    etype: str = "project",
    created: datetime,
    category: str | None = None,
    attrs: dict | None = None,
    tracking_tier: str = "active",
    merged_into: int | None = None,
) -> int:
    return int(
        session.execute(
            text(
                """
                INSERT INTO entities
                  (entity_type, canonical_name, category, created_at, attrs,
                   tracking_tier, merged_into)
                VALUES (:t, :n, :cat, :c, CAST(:a AS JSONB), :tier, :m) RETURNING id
                """
            ),
            {
                "t": etype,
                "n": name,
                "cat": category,
                "c": created,
                "a": json.dumps(attrs or {}),
                "tier": tracking_tier,
                "m": merged_into,
            },
        ).scalar_one()
    )


def _metric(session: Session, entity_id: int, metric: str, day: datetime, value: float) -> None:
    session.execute(
        text(
            "INSERT INTO entity_metrics_daily (entity_id, metric, day, value) "
            "VALUES (:e, :m, :d, :v)"
        ),
        {"e": entity_id, "m": metric, "d": day.date(), "v": value},
    )


def _tier(session: Session, entity_id: int) -> str:
    return str(
        session.execute(
            text("SELECT tracking_tier FROM entities WHERE id = :e"), {"e": entity_id}
        ).scalar_one()
    )


def _decision(session: Session, entity_id: int) -> dict | None:
    row = (
        session.execute(
            text(
                "SELECT decision, sector, decided_by, model FROM discovery_triage_decisions "
                "WHERE entity_id = :e"
            ),
            {"e": entity_id},
        )
        .mappings()
        .one_or_none()
    )
    return dict(row) if row else None


def _attrs(session: Session, entity_id: int) -> dict:
    return dict(
        session.execute(
            text("SELECT attrs FROM entities WHERE id = :e"), {"e": entity_id}
        ).scalar_one()
    )


_T0 = datetime(2024, 1, 1, tzinfo=UTC)


# --- deterministic threshold path (mock provider) ---------------------------


def test_github_over_threshold_is_tracked(clean_db: Session, monkeypatch) -> None:
    session = clean_db
    monkeypatch.setattr(settings, "llm_provider", "mock")
    eid = _entity(session, "hot", created=_T0, attrs={"anchors": {"github": "acme/hot"}})
    _metric(session, eid, "gh_stars", _T0, settings.triage_github_star_threshold + 10)
    session.flush()

    stats = run_triage(session)
    assert stats.candidates == 1 and stats.tracked == 1 and stats.by_threshold == 1
    assert _tier(session, eid) == "active"
    dec = _decision(session, eid)
    assert dec == {"decision": "track", "sector": None, "decided_by": "threshold", "model": None}
    assert _attrs(session, eid)["discovered_by"] == "discovery+threshold"
    assert _attrs(session, eid)["triage"]["decision"] == "track"


def test_github_under_threshold_is_archived(clean_db: Session, monkeypatch) -> None:
    session = clean_db
    monkeypatch.setattr(settings, "llm_provider", "mock")
    eid = _entity(session, "cold", created=_T0, attrs={"anchors": {"github": "acme/cold"}})
    _metric(session, eid, "gh_stars", _T0, settings.triage_github_star_threshold - 1)
    session.flush()

    stats = run_triage(session)
    assert stats.skipped == 1 and stats.by_threshold == 1
    assert _tier(session, eid) == "archived"
    assert _decision(session, eid)["decision"] == "skip"
    # A skipped entity gets a triage breadcrumb but no discovered_by marker.
    assert "discovered_by" not in _attrs(session, eid)


def test_hf_over_threshold_is_tracked(clean_db: Session, monkeypatch) -> None:
    session = clean_db
    monkeypatch.setattr(settings, "llm_provider", "mock")
    eid = _entity(
        session, "model-x", etype="model", created=_T0, attrs={"anchors": {"hf": "org/model-x"}}
    )
    _metric(session, eid, "hf_downloads_30d", _T0, settings.triage_hf_downloads_threshold + 1)
    session.flush()

    run_triage(session)
    assert _tier(session, eid) == "active"
    assert _decision(session, eid)["decision"] == "track"


def test_paper_and_person_excluded_from_candidates(clean_db: Session, monkeypatch) -> None:
    session = clean_db
    monkeypatch.setattr(settings, "llm_provider", "mock")
    # A paper carrying (implausibly) high stars, and a graph-minted person — both are graph-derived
    # types, so neither is a discovery candidate: no decision, tier untouched.
    paper = _entity(session, "2301.00001", etype="paper", created=_T0,
                    attrs={"anchors": {"arxiv": "2301.00001", "github": "x/y"}})
    _metric(session, paper, "gh_stars", _T0, settings.triage_github_star_threshold + 999)
    person = _entity(session, "octocat", etype="person", created=_T0,
                     attrs={"anchors": {"github": "user:octocat"}})
    session.flush()

    stats = run_triage(session)
    assert stats.candidates == 0
    assert _decision(session, paper) is None and _decision(session, person) is None
    assert _tier(session, paper) == "active" and _tier(session, person) == "active"


def test_paper_is_never_threshold_tracked() -> None:
    # The defensive guard in the pure helper: even a paper that cleared every bar is not tracked.
    huge = settings.triage_github_star_threshold + settings.triage_hf_downloads_threshold
    assert _threshold_track("paper", ["github", "hf", "arxiv"], huge, huge, huge) is False
    assert _threshold_track(
        "project", ["github"], settings.triage_github_star_threshold, None, None
    )


def test_seed_and_merged_and_non_active_excluded(clean_db: Session, monkeypatch) -> None:
    session = clean_db
    monkeypatch.setattr(settings, "llm_provider", "mock")
    survivor = _entity(session, "survivor", created=_T0)
    seeded = _entity(session, "seeded", created=_T0, attrs={"seed_category": "llm-serving"})
    merged = _entity(session, "merged", created=_T0, merged_into=survivor,
                     attrs={"anchors": {"github": "a/b"}})
    archived = _entity(session, "already", created=_T0, tracking_tier="archived",
                       attrs={"anchors": {"github": "c/d"}})
    session.flush()

    stats = run_triage(session)
    # Only ``survivor`` is a candidate; seeded/merged/archived are all excluded.
    assert stats.candidates == 1
    assert _decision(session, seeded) is None
    assert _decision(session, merged) is None
    assert _decision(session, archived) is None
    assert _tier(session, archived) == "archived"


# --- ai path (stubbed complete_triage) --------------------------------------


def test_ai_track_records_provenance(clean_db: Session, monkeypatch) -> None:
    session = clean_db
    monkeypatch.setattr(settings, "llm_provider", "claude_cli")
    monkeypatch.setattr(
        triage_mod, "complete_triage", lambda facts: {"decision": "track", "sector": "robotics"}
    )
    eid = _entity(session, "arm", created=_T0, attrs={"anchors": {"github": "acme/arm"}})
    session.flush()

    stats = run_triage(session)
    assert stats.tracked == 1 and stats.by_ai == 1 and stats.by_threshold == 0
    dec = _decision(session, eid)
    assert dec["decision"] == "track" and dec["decided_by"] == "ai"
    assert dec["sector"] == "robotics"
    assert dec["model"] == f"claude_cli:{settings.claude_cli_model}"
    assert _tier(session, eid) == "active"
    assert _attrs(session, eid)["discovered_by"] == "discovery+ai"


def test_ai_skip_archives(clean_db: Session, monkeypatch) -> None:
    session = clean_db
    monkeypatch.setattr(settings, "llm_provider", "claude_cli")
    monkeypatch.setattr(triage_mod, "complete_triage", lambda facts: {"decision": "skip"})
    # High stars would threshold-track, but the AI says skip — the AI decision wins.
    eid = _entity(session, "noise", created=_T0, attrs={"anchors": {"github": "acme/noise"}})
    _metric(session, eid, "gh_stars", _T0, settings.triage_github_star_threshold + 5000)
    session.flush()

    stats = run_triage(session)
    assert stats.skipped == 1 and stats.by_ai == 1
    assert _tier(session, eid) == "archived"
    dec = _decision(session, eid)
    assert dec["decided_by"] == "ai" and dec["model"] is not None and dec["sector"] is None


# --- idempotency + dry-run --------------------------------------------------


def test_already_decided_is_not_re_triaged(clean_db: Session, monkeypatch) -> None:
    session = clean_db
    monkeypatch.setattr(settings, "llm_provider", "mock")
    eid = _entity(session, "seen", created=_T0, attrs={"anchors": {"github": "acme/seen"}})
    _metric(session, eid, "gh_stars", _T0, settings.triage_github_star_threshold + 10)
    session.flush()

    first = run_triage(session)
    assert first.candidates == 1
    session.flush()
    second = run_triage(session)
    assert second.candidates == 0 and second.tracked == 0 and second.skipped == 0
    # Exactly one decision row survives.
    n = session.execute(
        text("SELECT count(*) FROM discovery_triage_decisions WHERE entity_id = :e"), {"e": eid}
    ).scalar_one()
    assert n == 1


def test_dry_run_computes_stats_but_writes_nothing(clean_db: Session, monkeypatch) -> None:
    session = clean_db
    monkeypatch.setattr(settings, "llm_provider", "mock")
    hot = _entity(session, "hot", created=_T0, attrs={"anchors": {"github": "a/hot"}})
    _metric(session, hot, "gh_stars", _T0, settings.triage_github_star_threshold + 10)
    cold = _entity(session, "cold", created=_T0, attrs={"anchors": {"github": "a/cold"}})
    _metric(session, cold, "gh_stars", _T0, 1)
    session.flush()

    stats = run_triage(session, dry_run=True)
    assert stats.candidates == 2 and stats.tracked == 1 and stats.skipped == 1
    # No rows written, no tiers changed.
    assert _decision(session, hot) is None and _decision(session, cold) is None
    assert _tier(session, hot) == "active" and _tier(session, cold) == "active"
    n = session.execute(
        text("SELECT count(*) FROM discovery_triage_decisions")
    ).scalar_one()
    assert n == 0
