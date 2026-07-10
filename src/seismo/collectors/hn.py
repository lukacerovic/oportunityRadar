"""Hacker News via the Algolia Search API (doc 03 §2.2). Free, no key, fully historical —
the hindcast workhorse. Attention evidence only.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any
from urllib.parse import urlparse

import httpx

from seismo.collectors.base import RateLimiter, RawEventDraft, TrackTarget, Window
from seismo.collectors.http import make_client

BASE = "https://hn.algolia.com/api/v1/search_by_date"

# URL-based capture is higher precision than keywords (doc 03 §2.2).
CAPTURE_DOMAINS = {"github.com", "arxiv.org", "huggingface.co"}
KEYWORDS = {
    "llm",
    "agent",
    "inference",
    "rag",
    "transformer",
    "fine-tune",
    "embedding",
    "diffusion",
}
POINTS_FLOOR = 50
MAX_PAGES = 20


class HackerNewsCollector:
    source = "hn"

    def __init__(self, *, client: httpx.Client | None = None, min_interval_s: float = 0.2):
        self._client = client or make_client()
        self._limiter = RateLimiter(min_interval_s)

    def discover(self, window: Window) -> list[RawEventDraft]:
        drafts: list[RawEventDraft] = []
        page = 0
        while page < MAX_PAGES:
            self._limiter.wait()
            params: dict[str, str | int] = {
                "tags": "story",
                "numericFilters": (
                    f"created_at_i>={int(window.since.timestamp())},"
                    f"created_at_i<{int(window.until.timestamp())}"
                ),
                "hitsPerPage": 100,
                "page": page,
            }
            resp = self._client.get(BASE, params=params)
            resp.raise_for_status()
            data = resp.json()
            for hit in data.get("hits", []):
                if self._relevant(hit):
                    drafts.append(self._draft(hit))
            if page + 1 >= data.get("nbPages", 1):
                break
            page += 1
        return drafts

    def track(self, targets: list[TrackTarget], window: Window) -> list[RawEventDraft]:
        # story_snapshot (attention decay at +24h/+72h) is a Wave-later add; discovery suffices.
        return []

    @staticmethod
    def _relevant(hit: dict[str, Any]) -> bool:
        if (hit.get("points") or 0) >= POINTS_FLOOR:
            return True
        url = hit.get("url")
        if url:
            host = (urlparse(url).hostname or "").lower().removeprefix("www.")
            if any(host == d or host.endswith("." + d) for d in CAPTURE_DOMAINS):
                return True
        title = (hit.get("title") or "").lower()
        return any(k in title for k in KEYWORDS)

    @staticmethod
    def _draft(hit: dict[str, Any]) -> RawEventDraft:
        occurred = datetime.fromtimestamp(int(hit["created_at_i"]), tz=UTC)
        return RawEventDraft(
            source="hn",
            source_event_uid=str(hit["objectID"]),
            event_type="story",
            occurred_at=occurred,
            payload=hit,
        )
