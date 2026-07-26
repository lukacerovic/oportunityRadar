"""Community summary generation.

v1 keeps a deterministic fallback summary so the pipeline works with the repo's default mock LLM
configuration. A richer provider-backed summary can replace this without changing persistence.
The summary is source-labelled ("GitHub", "Hacker News", "Hugging Face") from the threads found.
"""

from __future__ import annotations

from typing import Any

from seismo.community.relevance import CommunityThread
from seismo.community.targets import CommunityTarget

_SOURCE_LABEL = {"github": "GitHub", "hn": "Hacker News", "hf": "Hugging Face"}


def summarize_threads(target: CommunityTarget, threads: list[CommunityThread]) -> dict[str, Any]:
    if not threads:
        return {
            "status": "not_found",
            "summary": (
                "We could not find meaningful public community discussion about this project yet."
            ),
            "sentiment": None,
            "confidence": "high",
            "main_points": [],
            "concerns": [],
            "positive_signals": [],
            "threads": [],
            "searched_queries": [],
            "notes": ["No result passed the relevance threshold."],
        }

    total_comments = sum(t.comment_count or 0 for t in threads)
    confidence = "high" if len(threads) >= 3 and total_comments >= 30 else "medium"
    if len(threads) == 1 and total_comments < 10:
        confidence = "low"

    channels = sorted({t.channel for t in threads})
    source_label = _SOURCE_LABEL.get(threads[0].source, threads[0].source)
    summary = (
        f"Found {len(threads)} relevant {source_label} discussion"
        f"{'s' if len(threads) != 1 else ''} about {target.canonical_name}. "
        "Review the linked threads for the actual community context; automated sentiment is "
        "kept conservative until a fuller comment summarizer is enabled."
    )
    return {
        "status": "found",
        "summary": summary,
        "sentiment": "unclear",
        "confidence": confidence,
        "main_points": [
            f"Relevant discussion appears in {', '.join(channels)}.",
            f"Matched {total_comments} total comments across selected threads.",
        ],
        "concerns": [],
        "positive_signals": [],
        "threads": [_thread_json(t) for t in threads],
        "searched_queries": [],
        "notes": ["Deterministic v1 summary; thread links are the source of truth."],
    }


# Bound persisted discussion text so a thread with hundreds of long comments can't bloat the
# JSONB row. Each comment is truncated; the total kept per thread is already capped upstream by
# ``community_max_comments_per_thread``.
_COMMENT_CHARS = 1500


def _thread_json(thread: CommunityThread) -> dict[str, Any]:
    return {
        "id": thread.thread_id,
        "title": thread.title,
        "source": thread.source,
        "channel": thread.channel,
        "url": thread.url,
        "score": thread.score,
        "comment_count": thread.comment_count,
        "created_at": thread.created_at.isoformat() if thread.created_at else None,
        "relevance_score": thread.relevance_score,
        "matched_queries": thread.matched_queries,
        # The actual discussion text — the point of the collector. Bounded per comment.
        "comments": [c[:_COMMENT_CHARS] for c in thread.comments],
    }
