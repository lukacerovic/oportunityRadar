"""Cross-source community verdict — one AI-distilled answer to "what does the community think?".

After the per-source collectors (github / hf / hn) have written their rows, this pass reads an
entity's collected discussion comments *across all sources* and asks the LLM for one structured
verdict: overall sentiment (+ a 0–100 score), what people like, what they complain about, the key
themes, and a couple of representative quotes. It is stored as a synthetic ``source='summary'`` row
in ``entity_community_research`` (no schema change) so the dossier API serves it alongside the
per-source rows, and the dashboard renders it as the "Community Verdict" panel.

Runs on the pluggable LLM (:mod:`seismo.checkpoints.llm`): ``mock`` returns the deterministic
fallback ($0, offline), ``ollama`` distills locally ($0), ``anthropic`` for production quality.
"""

from __future__ import annotations

import json
from collections.abc import Iterator, Sequence
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from datetime import UTC, datetime
from decimal import Decimal
from typing import Any

from sqlalchemy import text
from sqlalchemy.orm import Session

from seismo.checkpoints.llm import LLMResult, complete_community

SUMMARY_SOURCE = "summary"
_SOURCE_LABEL = {"github": "GitHub", "hf": "Hugging Face", "hn": "Hacker News"}
_MAX_COMMENTS_PER_THREAD = 8  # bound the prompt: enough signal, small enough for a local 7B model
_MAX_THREADS = 8
_COMMENT_CHARS = 600

_SENTIMENTS = [
    "positive",
    "mostly_positive",
    "mixed",
    "mostly_negative",
    "negative",
    "insufficient_data",
]

SYSTEM_PROMPT = (
    "You summarize public community discussion about a software project or AI model for portfolio "
    "managers who will not read the underlying threads. Your summary is the only thing they see.\n"
    "\n"
    "Report only what the supplied comments actually say. Do not add outside knowledge, do not "
    "predict adoption or future trajectory, and never invent praise or complaints. If a commenter "
    "reports running the project in production, evaluating it, or abandoning it, that is a fact "
    "stated in the comments — include it. Anything you cannot point to in a comment does not "
    "belong in the verdict.\n"
    "\n"
    "Judge tone by what commenters mean, not by the words alone. Sarcasm, rhetorical questions and "
    "backhanded praise are criticism, not approval.\n"
    "\n"
    "Threads are matched by name and some may be about a DIFFERENT product that happens to share "
    "it. Read each thread title and its comments: if a thread is plainly about something else, "
    "ignore it entirely rather than folding it in. If little or nothing is left after discarding "
    "the mismatched threads, use overall_sentiment='insufficient_data' and say in the summary that "
    "the matched discussion appears to be about a different project of the same name.\n"
    "\n"
    "Weight matters more than novelty. A point raised across many comments and threads is more "
    "important than a vivid one-off, and you must say which it is inside the item itself — e.g. "
    "'the dominant objection, raised in every thread' versus 'one commenter reported'. Order every "
    "list most significant first; only the first few items are displayed.\n"
    "\n"
    "Write each item as one short, self-contained sentence that makes sense without the thread. "
    "Be concrete: 'crashes above 8k context on A100s' beats 'stability issues'.\n"
    "\n"
    # Batch job, no human on the other end. Without this the model treats thin input as a request
    # it should clarify and answers "could you provide the comments?" — not something we can store.
    "This is an automated batch call with nobody to reply to. If the material is missing, empty, "
    "truncated or too thin to judge, do not ask for more: return overall_sentiment="
    "'insufficient_data' and state the reason in the summary."
)


def verdict_tool_schema() -> dict[str, Any]:
    return {
        "type": "object",
        "properties": {
            "overall_sentiment": {
                "type": "string",
                "enum": _SENTIMENTS,
                "description": (
                    "The balance of opinion across the comments. Use 'insufficient_data' when the "
                    "comments are too few, too short, or too off-topic to characterize — say so "
                    "plainly in the summary rather than guessing."
                ),
            },
            "sentiment_score": {
                "type": "integer",
                "minimum": 0,
                "maximum": 100,
                "description": (
                    "0 = very negative, 100 = very positive. Must agree with the balance of "
                    "positive_signals and concerns below."
                ),
            },
            "summary": {
                "type": "string",
                "description": (
                    "Two or three sentences: what the community is actually discussing, where "
                    "opinion concentrates, and where it splits. State whether the praise and the "
                    "criticism come from the same commenters or different ones."
                ),
            },
            "positive_signals": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "Concrete things people report liking, or succeeding with. Most significant "
                    "first. Do not include sarcastic or backhanded remarks here."
                ),
            },
            "concerns": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "Concrete problems, complaints, limitations or blockers people raise. Most "
                    "significant first. Nearly every real discussion contains some criticism — "
                    "return an empty list only when the comments genuinely contain none, never "
                    "merely because the overall tone is favourable."
                ),
            },
            "main_points": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "The themes the discussion is about — topics, not judgements. Do not restate "
                    "items already listed in concerns or positive_signals."
                ),
            },
            "notable_quotes": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "One or two short verbatim comments (trimmed) that represent the discussion as "
                    "a whole. Choose typical over punchy — the first is the only one displayed."
                ),
            },
        },
        "required": [
            "overall_sentiment",
            "sentiment_score",
            "summary",
            "positive_signals",
            "concerns",
            "main_points",
        ],
    }


@dataclass
class _SourceData:
    source: str
    threads: list[dict[str, Any]]


@dataclass
class CommunitySynthesisStats:
    selected: int = 0
    summarized: int = 0
    skipped: int = 0
    failed: int = 0
    cost_usd: Decimal = field(default_factory=lambda: Decimal(0))
    input_tokens: int = 0
    output_tokens: int = 0
    stopped_reason: str | None = None

    def as_note(self) -> str:
        note = (
            f"selected={self.selected} summarized={self.summarized} "
            f"skipped={self.skipped} failed={self.failed} cost=${self.cost_usd:.4f}"
        )
        if self.stopped_reason:
            note += f" stopped={self.stopped_reason}"
        return note


# Why ``--force`` must not be combined with ``--limit``: persistence here is INSERT-only, and
# ``force`` drops the staleness filter while keeping a stable ``ORDER BY ... LIMIT``. Nothing ever
# leaves the selection, so a drain loop re-summarizes the same top N forever — billing every pass.
# ``redo_before`` exists precisely so a batched re-run terminates.
FORCE_LIMIT_ERROR = (
    "--force with --limit never terminates: verdicts are INSERT-only, so the same top N is "
    "re-selected (and re-billed) on every pass. Use --redo-before <ISO timestamp> to redo the "
    "backlog in batches, or --force with --entity-id to redo a single entity."
)

# Work items handed to the pool before results are persisted and (optionally) committed. Keeping
# it a small multiple of the worker count bounds how much work a crash can lose.
_CHUNK_FACTOR = 4


def run_community_synthesis(
    session: Session,
    *,
    as_of: datetime,
    limit: int | None = None,
    entity_id: int | None = None,
    force: bool = False,
    redo_before: datetime | None = None,
    concurrency: int = 1,
    budget_usd: float | None = None,
    checkpoint: bool = False,
) -> CommunitySynthesisStats:
    """Synthesize a verdict for entities whose per-source discussion is newer than their last
    summary (or that have none). Idempotent: the ``summary`` row's ``researched_at`` gates re-runs
    exactly like the per-source cadence.

    ``redo_before`` re-selects entities whose newest verdict predates that timestamp — the
    terminating way to redo the backlog after a prompt or model change, since each entity leaves
    the selection as soon as it is re-summarized. ``force`` ignores the cadence entirely and is
    only safe without ``--limit`` or on a single ``entity_id`` (see :data:`FORCE_LIMIT_ERROR`).

    ``concurrency`` fans the LLM calls out across threads; the ``Session`` is not thread-safe, so
    every read and write stays on the calling thread and only the network call is parallel.
    ``budget_usd`` stops the run once accumulated spend reaches it (checked per chunk, so the
    overshoot is bounded by one chunk). ``checkpoint`` commits after each chunk so a crash part-way
    through a long run keeps the verdicts already paid for.
    """
    if force and limit is not None and entity_id is None:
        raise ValueError(FORCE_LIMIT_ERROR)

    targets = _select_targets(
        session,
        as_of=as_of,
        limit=limit,
        entity_id=entity_id,
        force=force,
        redo_before=redo_before,
    )
    stats = CommunitySynthesisStats(selected=len(targets))
    budget = Decimal(str(budget_usd)) if budget_usd and budget_usd > 0 else None
    workers = max(1, concurrency)

    for chunk in _chunks(targets, workers * _CHUNK_FACTOR):
        if budget is not None and stats.cost_usd >= budget:
            stats.stopped_reason = f"llm_budget_usd ${budget} reached"
            break
        billable: list[tuple[int, str, list[_SourceData]]] = []
        for eid, name in chunk:
            sources = _load_sources(session, eid)
            kpis = _kpis(sources)
            # Gate on *comments*, not threads. A third of collected entities carry thread titles
            # with no comment bodies (issues nobody replied to), and there is nothing to summarize
            # from a title alone — the model correctly refuses, which used to burn a paid call and
            # then land a `failed` row that got retried on every subsequent run.
            if kpis["comment_count"] > 0:
                billable.append((eid, name, sources))
            else:
                _persist(session, eid, _empty_verdict(kpis), "mock")
                stats.skipped += 1
        for (eid, _name, _sources), outcome in zip(
            billable, _synthesize_many(billable, workers), strict=True
        ):
            if isinstance(outcome, Exception):
                _persist(session, eid, _failed_verdict(outcome), None)
                stats.failed += 1
                continue
            verdict, result = outcome
            _persist(session, eid, verdict, result.model)
            stats.summarized += 1
            stats.cost_usd += result.cost_usd
            stats.input_tokens += result.input_tokens
            stats.output_tokens += result.output_tokens
        if checkpoint:
            session.commit()
    return stats


def _chunks(items: Sequence[Any], size: int) -> Iterator[Sequence[Any]]:
    for start in range(0, len(items), max(1, size)):
        yield items[start : start + max(1, size)]


def _synthesize_many(
    items: Sequence[tuple[int, str, list[_SourceData]]], workers: int
) -> list[tuple[dict[str, Any], LLMResult] | Exception]:
    """Run one chunk's LLM calls. Pure network I/O, so threads are the right tool. A bad generation
    is *returned* rather than raised so that one entity cannot abort the batch."""

    def one(
        item: tuple[int, str, list[_SourceData]],
    ) -> tuple[dict[str, Any], LLMResult] | Exception:
        try:
            return _synthesize(item[1], item[2])
        except Exception as exc:
            return exc

    if workers == 1 or len(items) <= 1:
        return [one(item) for item in items]
    with ThreadPoolExecutor(max_workers=workers) as pool:
        return list(pool.map(one, items))


def _synthesize(name: str, sources: list[_SourceData]) -> tuple[dict[str, Any], LLMResult]:
    kpis = _kpis(sources)
    fallback = _deterministic_verdict(sources, kpis)
    result = complete_community(
        SYSTEM_PROMPT, _user_prompt(name, sources), verdict_tool_schema(), fallback=fallback
    )
    return _shape(result.content, kpis), result


def _shape(content: dict[str, Any], kpis: dict[str, Any]) -> dict[str, Any]:
    sentiment = content.get("overall_sentiment")
    if sentiment not in _SENTIMENTS:
        sentiment = "mixed"
    score = content.get("sentiment_score")
    try:
        score = max(0, min(100, int(score)))
    except (TypeError, ValueError):
        score = 50
    return {
        "status": "found",
        "summary": str(content.get("summary") or "").strip()
        or "Community discussion was collected but produced no summary.",
        "sentiment": sentiment,
        "sentiment_score": score,
        "confidence": _confidence(kpis),
        "main_points": _str_list(content.get("main_points")),
        "concerns": _str_list(content.get("concerns")),
        "positive_signals": _str_list(content.get("positive_signals")),
        "notable_quotes": _str_list(content.get("notable_quotes")),
        "kpis": kpis,
        "threads": [],  # the verdict is a synthesis; per-source rows hold the actual threads
    }


def _user_prompt(name: str, sources: list[_SourceData]) -> str:
    lines = [f"Project/model: {name}", ""]
    for sd in sources:
        lines.append(f"## Source: {_SOURCE_LABEL.get(sd.source, sd.source)}")
        for t in sd.threads[:_MAX_THREADS]:
            lines.append(f"- Thread: {t.get('title') or '(untitled)'} ({t.get('channel') or ''})")
            for c in (t.get("comments") or [])[:_MAX_COMMENTS_PER_THREAD]:
                text_c = " ".join(str(c).split())[:_COMMENT_CHARS]
                if text_c:
                    lines.append(f"    • {text_c}")
        lines.append("")
    lines.append(
        "Return the community verdict. Base sentiment strictly on the comments above."
    )
    return "\n".join(lines)


def _deterministic_verdict(sources: list[_SourceData], kpis: dict[str, Any]) -> dict[str, Any]:
    labels = ", ".join(_SOURCE_LABEL.get(s.source, s.source) for s in sources)
    return {
        "overall_sentiment": "mixed",
        "sentiment_score": 50,
        "summary": (
            f"Collected {kpis['thread_count']} discussion thread(s) with "
            f"{kpis['comment_count']} comment(s) across {labels}. Enable an LLM provider "
            "(ollama/anthropic) for a sentiment-graded summary."
        ),
        "positive_signals": [],
        "concerns": [],
        "main_points": [],
        "notable_quotes": [],
    }


def _kpis(sources: list[_SourceData]) -> dict[str, Any]:
    thread_count = sum(len(s.threads) for s in sources)
    comment_count = sum(
        len(t.get("comments") or []) for s in sources for t in s.threads
    )
    return {
        "sources": [s.source for s in sources if s.threads],
        "thread_count": thread_count,
        "comment_count": comment_count,
    }


def _confidence(kpis: dict[str, Any]) -> str:
    threads, comments = kpis["thread_count"], kpis["comment_count"]
    if threads >= 3 and comments >= 20:
        return "high"
    if threads >= 1 and comments >= 5:
        return "medium"
    return "low"


def _empty_verdict(kpis: dict[str, Any] | None = None) -> dict[str, Any]:
    """No comment text to summarize. ``kpis`` still reports the threads that *were* collected, so
    the dashboard can say "5 issues, none with replies" rather than implying nothing was found."""
    kpis = kpis or {"sources": [], "thread_count": 0, "comment_count": 0}
    threads = kpis["thread_count"]
    return {
        "status": "not_found",
        "summary": (
            f"Collected {threads} discussion thread(s), but none carry comment text to summarize."
            if threads
            else "No quotable community discussion was found across sources yet."
        ),
        "sentiment": "insufficient_data",
        "sentiment_score": None,
        "confidence": "high",
        "main_points": [],
        "concerns": [],
        "positive_signals": [],
        "notable_quotes": [],
        "kpis": kpis,
        "threads": [],
    }


def _failed_verdict(exc: Exception) -> dict[str, Any]:
    return {
        "status": "failed",
        "summary": "Community verdict synthesis failed and will be retried.",
        "error": f"{type(exc).__name__}: {exc}"[:500],
        "sentiment": None,
        "sentiment_score": None,
        "confidence": "low",
        "main_points": [],
        "concerns": [],
        "positive_signals": [],
        "notable_quotes": [],
        "kpis": {"sources": [], "thread_count": 0, "comment_count": 0},
        "threads": [],
    }


def _str_list(value: Any) -> list[str]:
    if not isinstance(value, list):
        return []
    return [str(v).strip() for v in value if str(v).strip()][:8]


def _select_targets(
    session: Session,
    *,
    as_of: datetime,
    limit: int | None,
    entity_id: int | None,
    force: bool,
    redo_before: datetime | None = None,
) -> list[tuple[int, str]]:
    """Entities whose newest per-source discussion is newer than their newest verdict (or that have
    none), hottest-collected first. ``force`` re-selects even if the verdict is current;
    ``redo_before`` re-selects only those not yet re-summarized since that timestamp, which is what
    makes a batched re-run drain instead of looping (see :data:`FORCE_LIMIT_ERROR`)."""
    if redo_before is not None:
        # Re-selects regardless of status, so failures are covered without a special case — and
        # without the infinite-loop risk that adding one would create in a drain loop.
        stale_clause = "AND (summ.last_summary IS NULL OR summ.last_summary < :redo_before)"
    elif force:
        stale_clause = ""
    else:
        # A `failed` verdict is written with researched_at = now(), which is newer than the source
        # rows — so without the status check a transient failure (rate limit, a reply that wasn't
        # JSON) would lock that entity out of every subsequent run. Re-running the command is the
        # retry mechanism, so failures must stay selectable.
        stale_clause = (
            "AND (summ.last_summary IS NULL OR summ.last_summary < src.last_src"
            " OR summ.last_status = 'failed')"
        )
    entity_clause = "AND e.id = :entity_id" if entity_id is not None else ""
    limit_clause = "LIMIT :limit" if limit is not None else ""
    rows = session.execute(
        text(
            f"""
            WITH src AS (
              SELECT entity_id,
                     max(researched_at) AS last_src,
                     bool_or(status = 'found') AS any_found
              FROM entity_community_research
              WHERE source IN ('github', 'hf', 'hn') AND researched_at <= :as_of
              GROUP BY entity_id
            ),
            summ AS (
              SELECT DISTINCT ON (entity_id)
                     entity_id, researched_at AS last_summary, status AS last_status
              FROM entity_community_research
              WHERE source = '{SUMMARY_SOURCE}'
              ORDER BY entity_id, researched_at DESC, id DESC
            )
            SELECT e.id, e.canonical_name
            FROM src
            JOIN entities e ON e.id = src.entity_id
            LEFT JOIN summ ON summ.entity_id = src.entity_id
            WHERE src.any_found = true
              AND e.merged_into IS NULL
              AND e.tracking_tier <> 'archived'
              {stale_clause}
              {entity_clause}
            ORDER BY src.last_src DESC, e.id
            {limit_clause}
            """
        ),
        {
            "as_of": as_of,
            **({"limit": limit} if limit is not None else {}),
            **({"entity_id": entity_id} if entity_id is not None else {}),
            **({"redo_before": redo_before} if redo_before is not None else {}),
        },
    ).all()
    return [(int(r[0]), str(r[1])) for r in rows]


def _load_sources(session: Session, entity_id: int) -> list[_SourceData]:
    rows = (
        session.execute(
            text(
                """
                SELECT DISTINCT ON (source) source, status, result
                FROM entity_community_research
                WHERE entity_id = :e AND source IN ('github', 'hf', 'hn')
                ORDER BY source, researched_at DESC, id DESC
                """
            ),
            {"e": entity_id},
        )
        .mappings()
        .all()
    )
    out: list[_SourceData] = []
    for row in rows:
        # The status filter must come *after* picking the newest row per source, never inside the
        # query. Filtering first makes a later `not_found` invisible — it would keep resurrecting
        # the last row that happened to succeed, so a re-collection that deliberately finds nothing
        # (a relevance fix dropping contaminated threads, a deleted repo) never takes effect. Echo
        # kept summarizing four Amazon smart-speaker threads for exactly this reason, long after
        # its HN row had been re-collected as not_found.
        if row["status"] != "found":
            continue
        threads = (row["result"] or {}).get("threads") or []
        if threads:
            out.append(_SourceData(source=row["source"], threads=threads))
    return out


def _persist(session: Session, entity_id: int, result: dict[str, Any], model: str | None) -> None:
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
            "entity_id": entity_id,
            "source": SUMMARY_SOURCE,
            "status": result["status"],
            "query_set": json.dumps({"synthesis": True}),
            "result": json.dumps(result),
            "model": model,
            "researched_at": datetime.now(UTC),
        },
    )
