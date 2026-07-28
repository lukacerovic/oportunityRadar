"""``seismo sanity`` orchestrator — the content-quality checkpoint.

Collectors record; they never interpret (doc 03 §1). This is a separate checkpoint layer (CI
invariant-3 requires any LLM SDK usage to live under ``checkpoints/``) that runs *after*
collection/enrichment: it judges whether a freshly-collected raw event's free text (README, model
card, launch page, HN discussion, paper abstract) is legible, on-topic, substantive content, and may
propose a cosmetically-cleaned version for display — without ever mutating ``raw_events`` itself
(doc 02 §1: raw events are immutable). A ``reject`` verdict just means "don't feature this text" —
recorded as a separate ``content_sanity_checks`` row, never a delete of the source event.

Batches ``BATCH_SIZE`` raw events per LLM call — unlike comprehend/brief/council (triggered/gated to
a handful of entities), this runs over every freshly-collected text event, so per-row calls would be
far too expensive. Respects its own monthly budget ceiling (``SEISMO_SANITY_LLM_BUDGET_USD``),
tracked independently of the comprehension/brief budget so a heavy scrape day can't starve either
paid checkpoint.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from decimal import Decimal
from typing import Any

from pydantic import ValidationError
from sqlalchemy import text
from sqlalchemy.orm import Session

from seismo.checkpoints.contracts import ContentSanityBatch, sanity_tool_schema
from seismo.checkpoints.llm import complete_sanity
from seismo.config import settings

BATCH_SIZE = 10
_TEXT_CAP = 4000  # keep the batch prompt bounded regardless of each source's own truncation cap
# Every event_type across the collectors that carries substantive free text worth sanity-checking
# (doc 03 §16/Wave-3 enrichment) — payload->>'text', except paper_published which uses 'summary'.
_TEXT_EVENT_TYPES = (
    "repo_readme",
    "model_readme",
    "launch_page",
    "hn_discussion",
    "paper_published",
)

SYSTEM_PROMPT = (
    "You are the content-sanity checkpoint of a technology-monitoring system.\n"
    "Input: a batch of freshly-collected raw text snippets, each tagged with its raw_event_id.\n"
    "For EACH item, judge whether the text is legible, on-topic, substantive content — not "
    "boilerplate, not broken encoding, not an empty/placeholder page, not spam.\n"
    "Rules:\n"
    "- verdict='ok': legible, real content about the thing it claims to describe.\n"
    "- verdict='flagged': legible but low-substance (e.g. a one-line README, mostly "
    "badges/links) — still usable, just weak.\n"
    "- verdict='reject': garbage — broken encoding, empty/placeholder, unrelated spam, or "
    "scraped boilerplate with no real content.\n"
    "- cleaned_text: OPTIONAL. Only set it when the raw text has cosmetic noise worth "
    "stripping for display (repeated badge lines, raw HTML fragments, excessive blank lines) "
    "AND the underlying content is verdict='ok' or 'flagged'. Never fabricate or add content "
    "that isn't in the "
    "original — this is cosmetic cleanup, not rewriting. Omit it (null) when the raw text is "
    "already clean, or when verdict='reject'.\n"
    "- reasoning is REQUIRED for every item, one short sentence.\n"
    "Return exactly one item per raw_event_id given, in the same order."
)


@dataclass
class SanityStats:
    candidates: int = 0
    ok: int = 0
    flagged: int = 0
    rejected: int = 0
    skipped_budget: int = 0
    cost_usd: Decimal = field(default_factory=lambda: Decimal(0))

    def as_note(self) -> str:
        return (
            f"candidates={self.candidates} ok={self.ok} flagged={self.flagged} "
            f"rejected={self.rejected} skipped_budget={self.skipped_budget} "
            f"cost=${self.cost_usd:.4f}"
        )


def run_sanity(session: Session, as_of: datetime, *, limit: int | None = None) -> SanityStats:
    """Sanity-check every not-yet-checked raw event with substantive text, newest first, capped at
    ``limit`` (default 500 — a generous daily slice, not the whole backlog at once)."""
    stats = SanityStats()
    rows = _select_candidates(session, limit)
    stats.candidates = len(rows)
    if not rows:
        return stats

    month_spent = _month_spend(session, as_of)
    budget = Decimal(str(settings.sanity_llm_budget_usd))

    for i in range(0, len(rows), BATCH_SIZE):
        batch = rows[i : i + BATCH_SIZE]
        if settings.llm_provider != "mock" and month_spent >= budget:
            stats.skipped_budget += len(batch)
            continue

        result = _check_batch(batch)
        stats.cost_usd += result.cost_usd
        month_spent += result.cost_usd
        cost_per_row = result.cost_usd / len(batch) if batch else Decimal(0)

        by_id = {item["raw_event_id"]: item for item in result.content.get("items", [])}
        for row in batch:
            item = by_id.get(row["id"])
            if item is None:
                continue  # model dropped this row from the batch — leave unchecked, retry next run
            _store(session, row["id"], item, model=result.model, cost=cost_per_row)
            if item["verdict"] == "ok":
                stats.ok += 1
            elif item["verdict"] == "flagged":
                stats.flagged += 1
            else:
                stats.rejected += 1
    return stats


def _select_candidates(session: Session, limit: int | None) -> list[dict[str, Any]]:
    """Raw events with substantive text, not yet sanity-checked (NOT EXISTS) — same backlog-slice
    pattern as the enrich-* commands, newest first so today's scrape gets checked first."""
    rows = (
        session.execute(
            text(
                """
                SELECT re.id, re.event_type,
                       COALESCE(re.payload->>'text', re.payload->>'summary') AS body,
                       re.payload->>'title' AS title
                FROM raw_events re
                WHERE re.event_type = ANY(:types)
                  AND COALESCE(re.payload->>'text', re.payload->>'summary') IS NOT NULL
                  AND NOT EXISTS (
                    SELECT 1 FROM content_sanity_checks c WHERE c.raw_event_id = re.id
                  )
                ORDER BY re.occurred_at DESC
                LIMIT :limit
                """
            ),
            {"types": list(_TEXT_EVENT_TYPES), "limit": limit or 500},
        )
        .mappings()
        .all()
    )
    return [dict(r) for r in rows]


def _check_batch(batch: list[dict[str, Any]]) -> Any:
    lines = []
    for row in batch:
        body = (row["body"] or "")[:_TEXT_CAP]
        title = row.get("title") or ""
        lines.append(f"--- raw_event_id={row['id']} ---\ntitle: {title}\n{body}")
    user = "\n\n".join(lines)
    fallback = {
        "items": [
            {
                "raw_event_id": row["id"],
                "verdict": "ok",
                "reasoning": "Mock sanity check: no live model configured, defaulting to ok.",
                "cleaned_text": None,
            }
            for row in batch
        ]
    }
    result = complete_sanity(SYSTEM_PROMPT, user, sanity_tool_schema(), fallback=fallback)
    try:
        result.content = ContentSanityBatch.model_validate(result.content).model_dump()
    except ValidationError:
        # Fail closed to the neutral fallback rather than storing malformed output — leaving these
        # rows unchecked (not stored) is what lets the next `sanity` run retry them.
        result.content = fallback
    return result


def _store(
    session: Session, raw_event_id: int, item: dict[str, Any], *, model: str, cost: Decimal
) -> None:
    session.execute(
        text(
            """
            INSERT INTO content_sanity_checks
              (raw_event_id, verdict, reasoning, cleaned_text, model, cost_usd)
            VALUES (:rid, :v, :r, :c, :m, :cost)
            ON CONFLICT (raw_event_id) DO NOTHING
            """
        ),
        {
            "rid": raw_event_id,
            "v": item["verdict"],
            "r": item["reasoning"],
            "c": item.get("cleaned_text"),
            "m": model,
            "cost": cost,
        },
    )


def _month_spend(session: Session, as_of: datetime) -> Decimal:
    """Sum of sanity-check costs in ``as_of``'s calendar month — tracked separately from the
    comprehension/brief budget (see module docstring)."""
    month_start = as_of.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    total = session.execute(
        text(
            "SELECT COALESCE(SUM(cost_usd), 0) FROM content_sanity_checks"
            " WHERE created_at >= :start"
        ),
        {"start": month_start},
    ).scalar_one()
    return Decimal(str(total))
