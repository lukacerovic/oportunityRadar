"""Orchestration and persistence for community research.

Researches *one source at a time* for the entities due for it (see
``targets.select_community_targets``, which tracks cadence per source). The CLI fans out over
sources for ``--source all``. Each run
appends one ``entity_community_research`` row per (entity, source), so a project accumulates a
GitHub row, an HN row, and an HF row independently, each on its own refresh cadence.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from seismo.community.queries import generate_queries
from seismo.community.relevance import CommunityThread, score_thread
from seismo.community.sources import CommunityClient, make_client
from seismo.community.summarize import summarize_threads
from seismo.community.targets import CommunityTarget, select_community_targets
from seismo.config import settings


@dataclass
class CommunityRunStats:
    selected: int = 0
    researched: int = 0
    found: int = 0
    not_found: int = 0
    failed: int = 0
    dry_run: bool = False
    dry_targets: list[tuple[CommunityTarget, list[str]]] | None = None

    def as_note(self) -> str:
        if self.dry_run:
            return f"selected={self.selected} dry_run=true"
        return (
            f"selected={self.selected} researched={self.researched} "
            f"found={self.found} not_found={self.not_found} failed={self.failed}"
        )


def run_community_research(
    session: Session,
    *,
    source: str,
    as_of: datetime,
    limit: int | None = None,
    entity_id: int | None = None,
    force: bool = False,
    dry_run: bool = False,
    no_summarize: bool = False,
    client: CommunityClient | None = None,
) -> CommunityRunStats:
    limit = settings.community_research_daily_limit if limit is None else limit
    targets = select_community_targets(
        session, source, as_of=as_of, limit=limit, entity_id=entity_id, force=force
    )

    owns_client = client is None
    svc = client or make_client(source)
    try:
        # Only research entities this source can actually serve (GitHub/HF need the matching
        # anchor). Non-applicable entities are skipped silently — no wasted row, no bogus cadence.
        applicable = [t for t in targets if svc.applies_to(t)]
        dry_targets = [
            (t, generate_queries(t, limit=settings.community_search_queries_per_entity))
            for t in applicable
        ]
        if dry_run:
            return CommunityRunStats(
                selected=len(applicable), dry_run=True, dry_targets=dry_targets, researched=0
            )

        stats = CommunityRunStats(selected=len(applicable))
        for target, queries in dry_targets:
            try:
                threads = _research_target(svc, target, queries, no_summarize=no_summarize)
                result = summarize_threads(target, threads)
                result["searched_queries"] = queries
                status = result["status"]
                _persist(session, target, source, status, queries, result, "deterministic")
                stats.researched += 1
                if status == "found":
                    stats.found += 1
                else:
                    stats.not_found += 1
            except Exception as exc:
                result = {
                    "status": "failed",
                    "summary": "Community research failed and will be retried later.",
                    "error": f"{type(exc).__name__}: {exc}"[:1000],
                    "threads": [],
                    "searched_queries": queries,
                }
                _persist(session, target, source, "failed", queries, result, None)
                stats.failed += 1
    finally:
        if owns_client:
            svc.close()
    return stats


def _research_target(
    client: CommunityClient,
    target: CommunityTarget,
    queries: list[str],
    *,
    no_summarize: bool,
) -> list[CommunityThread]:
    by_id: dict[str, CommunityThread] = {}
    for candidate in client.fetch_threads(target, queries, limit=10):
        scored = score_thread(target, candidate)
        if scored.relevance_score < 60:
            continue
        existing = by_id.get(scored.thread_id)
        if existing is None or scored.relevance_score > existing.relevance_score:
            by_id[scored.thread_id] = scored
    threads = sorted(by_id.values(), key=lambda t: t.relevance_score, reverse=True)[
        : settings.community_max_threads_per_entity
    ]
    if not no_summarize:
        for thread in threads:
            thread.comments = client.comments(
                thread, limit=settings.community_max_comments_per_thread
            )
    return threads


def _persist(
    session: Session,
    target: CommunityTarget,
    source: str,
    status: str,
    queries: list[str],
    result: dict[str, Any],
    model: str | None,
) -> None:
    session.execute(
        text(
            """
            INSERT INTO entity_community_research
              (entity_id, source, status, query_set, result, model, researched_at)
            VALUES
              (:entity_id, :source, :status, CAST(:query_set AS JSONB),
               CAST(:result AS JSONB), :model, :researched_at)
            """
        ),
        {
            "entity_id": target.entity_id,
            "source": source,
            "status": status,
            "query_set": json.dumps({"queries": queries}),
            "result": json.dumps(result),
            "model": model,
            "researched_at": datetime.now(UTC),
        },
    )
