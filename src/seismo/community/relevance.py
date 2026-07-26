"""Source-agnostic community discussion model + deterministic relevance scoring.

A ``CommunityThread`` is one discussion *about* an entity we already track — a GitHub issue or
discussion, a Hacker News story, a Hugging Face model discussion. Scoring is identical across
sources: a thread that names the entity's precise anchor (repo, model id, arXiv id) is on-topic;
a bare name match on a short generic name is not. Threads pulled from the entity's *own* channel
(its repo's issues/discussions, its model's discussion tab) are inherently on-topic.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Any

from seismo.community.targets import CommunityTarget

# Sources whose threads live on the entity's *own* channel (the repo's issues/discussions, the
# model's discussion tab). Such a thread is by construction about the entity, so it earns a
# confidence bump on top of the anchor match its URL already carries.
NATIVE_SOURCES = {"github", "hf"}


@dataclass
class CommunityThread:
    thread_id: str
    title: str
    source: str  # github | hn | hf
    channel: str  # human label of where it lives: "GitHub Issues", "Hacker News", "HF Discussions"
    url: str
    score: int | None = None
    comment_count: int | None = None
    created_at: datetime | None = None
    body: str | None = None
    relevance_score: float = 0.0
    matched_queries: list[str] = field(default_factory=list)
    comments: list[str] = field(default_factory=list)
    # Client-internal handle for fetching this thread's comments (owner/repo, issue number, …).
    # Never persisted — see ``_thread_json`` in summarize.py.
    ref: dict[str, Any] | None = None


def score_thread(target: CommunityTarget, thread: CommunityThread) -> CommunityThread:
    """Score a candidate thread's relevance to ``target`` (0–100+). ``>= 60`` is kept."""
    haystack = " ".join([thread.title, thread.body or "", thread.url]).lower()
    score = 0.0
    anchors = target.anchors

    if _contains(haystack, anchors.get("github")):
        score += 60
    if _contains(haystack, anchors.get("arxiv")):
        score += 60
    if _contains(haystack, anchors.get("hf")):
        score += 60
    if _contains(haystack, _host_anchor(anchors.get("web"))):
        score += 30

    name = target.canonical_name.lower()
    if name and name in haystack:
        score += 25

    owner = (target.owner or "").lower()
    if owner and owner in haystack:
        score += 10

    if thread.source in NATIVE_SOURCES:
        score += 15
    if (thread.comment_count or 0) >= 10:
        score += 5
    if (thread.score or 0) >= 50:
        score += 5

    # Short generic names ("Crew", "Flow") are noisy unless a precise anchor also matched.
    if len(name) <= 6 and score < 60:
        score -= 25

    thread.relevance_score = max(score, thread.relevance_score)
    return thread


def _host_anchor(value: str | None) -> str | None:
    """The hostname of a ``web`` anchor, or ``None`` if the anchor is not a real address.

    A web anchor is meant to be the project's homepage, and matching one is worth 30 points — a
    third of the keep threshold. Some entities carry a bare word instead (the entity "Echo" stores
    ``web='echo'``), which matches any text containing that word and hands anchor credit to
    unrelated threads: Echo picked up four Amazon-smart-speaker HN stories that way, all scoring
    exactly 65. Only a host-shaped anchor is distinctive enough to earn the points.

    Reducing to the host also makes the match itself more reliable, since the URL a thread carries
    (an HN story's submitted link) rarely repeats the full path we stored.
    """
    if not value:
        return None
    host = value.strip().lower().split("://", 1)[-1].split("/", 1)[0].removeprefix("www.")
    return host if "." in host and len(host) > 3 else None


def _contains(haystack: str, needle: str | None) -> bool:
    return needle is not None and needle.lower() in haystack


def _int(value: Any) -> int | None:
    try:
        return int(value) if value is not None else None
    except (TypeError, ValueError):
        return None
