"""Hacker News community client — what people *said* about a known entity.

Distinct from ``collectors.hn`` (which uses ``search_by_date`` to *discover* new stories in a time
window). Here we run relevance search (``/search``) for an entity's anchors, then pull each hit's
comment tree from ``/items/<id>``. Free, no key. The two never fetch the same thing: discovery
captures that a story exists + its points; this captures the opinion in its comments.
"""

from __future__ import annotations

import html
import re
from datetime import UTC, datetime
from typing import Any

import httpx

from seismo.collectors.base import RateLimiter
from seismo.collectors.http import make_client
from seismo.community.relevance import CommunityThread, _int
from seismo.community.targets import CommunityTarget

SEARCH_URL = "https://hn.algolia.com/api/v1/search"
ITEM_URL = "https://hn.algolia.com/api/v1/items/{object_id}"
_TAG_RE = re.compile(r"<[^>]+>")


class HackerNewsCommunityClient:
    source = "hn"

    def __init__(self, *, client: httpx.Client | None = None, min_interval_s: float = 0.2):
        self._client = client or make_client()
        self._limiter = RateLimiter(min_interval_s)

    def applies_to(self, target: CommunityTarget) -> bool:
        # HN is a text-search source: it can look for any entity that yields at least one query.
        return bool(target.canonical_name or target.anchors)

    def fetch_threads(
        self, target: CommunityTarget, queries: list[str], *, limit: int
    ) -> list[CommunityThread]:
        threads: dict[str, CommunityThread] = {}
        for query in queries:
            self._limiter.wait()
            resp = self._client.get(
                SEARCH_URL, params={"query": query, "tags": "story", "hitsPerPage": limit}
            )
            resp.raise_for_status()
            for hit in resp.json().get("hits", []):
                thread = self._thread(hit, query)
                if thread is None:
                    continue
                existing = threads.get(thread.thread_id)
                if existing is None:
                    threads[thread.thread_id] = thread
                elif query not in existing.matched_queries:
                    existing.matched_queries.append(query)
        return list(threads.values())

    def comments(self, thread: CommunityThread, *, limit: int) -> list[str]:
        self._limiter.wait()
        try:
            resp = self._client.get(ITEM_URL.format(object_id=thread.thread_id))
        except httpx.TransportError:
            return []
        if resp.status_code >= 400:
            return []
        out: list[str] = []
        for child in resp.json().get("children", []):
            text = _clean(child.get("text"))
            if text:
                out.append(text)
            if len(out) >= limit:
                break
        return out

    def close(self) -> None:
        self._client.close()

    @staticmethod
    def _thread(hit: dict[str, Any], query: str) -> CommunityThread | None:
        object_id = str(hit.get("objectID") or "")
        if not object_id:
            return None
        # The openable link must be the HN *discussion* (where the comments are), never the story's
        # submitted URL — an HN "Show HN" of a repo submits the repo URL, so that would send the
        # user to GitHub instead of the conversation.
        url = f"https://news.ycombinator.com/item?id={object_id}"
        # The submitted URL (often the repo itself) is kept in ``body`` so relevance scoring still
        # gets its precise anchor match, without leaking into the display link.
        submitted = str(hit.get("url") or "").strip()
        body = " ".join(p for p in [_clean(hit.get("story_text")), submitted or None] if p) or None
        created_i = hit.get("created_at_i")
        return CommunityThread(
            thread_id=object_id,
            title=str(hit.get("title") or ""),
            source="hn",
            channel="Hacker News",
            url=url,
            score=_int(hit.get("points")),
            comment_count=_int(hit.get("num_comments")),
            created_at=datetime.fromtimestamp(int(created_i), tz=UTC) if created_i else None,
            body=body,
            matched_queries=[query],
        )


def _clean(value: str | None) -> str | None:
    if not value:
        return None
    text = html.unescape(_TAG_RE.sub(" ", value)).strip()
    return text or None
