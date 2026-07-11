"""GitHub via REST + Search API (doc 03 §2.1). Participation evidence.

Discovery: repos created in the window under topic/keyword queries, plus late-discovery of
risers. Tracking: daily ``repo_snapshot`` (stars/forks/...) for known repos. Auth is optional
but strongly recommended — the Search API is 10 req/min unauthenticated, 30 authenticated.
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import httpx

from seismo.collectors.base import RateLimiter, RawEventDraft, TrackTarget, Window
from seismo.collectors.http import make_client
from seismo.config import settings

SEARCH_URL = "https://api.github.com/search/repositories"
REPO_URL = "https://api.github.com/repos/{full_name}"
ACCEPT = "application/vnd.github+json"

# Broad-and-shallow discovery seeds (doc 03 §2.1). Kept small; tuned in config later.
TOPICS = ["llm", "agents", "rag", "inference", "ai-agents"]
MAX_PAGES = 3  # Search returns ≤100/page; 3 pages per topic is ample for a daily window


class GitHubCollector:
    source = "github"

    def __init__(
        self,
        *,
        token: str | None = None,
        client: httpx.Client | None = None,
        min_interval_s: float = 2.0,
    ):
        self._token = token if token is not None else (settings.github_token or None)
        self._client = client or make_client()
        self._limiter = RateLimiter(min_interval_s)

    def _headers(self) -> dict[str, str]:
        headers = {"Accept": ACCEPT}
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        return headers

    def discover(self, window: Window) -> list[RawEventDraft]:
        d1 = window.since.astimezone(UTC).date().isoformat()
        d2 = window.until.astimezone(UTC).date().isoformat()
        seen: dict[str, RawEventDraft] = {}
        for topic in TOPICS:
            query = f"topic:{topic} created:{d1}..{d2}"
            for page in range(1, MAX_PAGES + 1):
                self._limiter.wait()
                params: dict[str, str | int] = {
                    "q": query,
                    "sort": "stars",
                    "order": "desc",
                    "per_page": 100,
                    "page": page,
                }
                resp = self._client.get(SEARCH_URL, params=params, headers=self._headers())
                resp.raise_for_status()
                items = resp.json().get("items", [])
                for repo in items:
                    if repo.get("fork"):  # forks are never a discovery seed (doc 04 §6)
                        continue
                    draft = self._discovery_draft(repo)
                    seen[draft.source_event_uid] = draft
                if len(items) < 100:
                    break
        return list(seen.values())

    def track(self, targets: list[TrackTarget], window: Window) -> list[RawEventDraft]:
        drafts: list[RawEventDraft] = []
        for target in targets:
            self._limiter.wait()
            try:
                resp = self._client.get(
                    REPO_URL.format(full_name=target.native_id), headers=self._headers()
                )
            except httpx.TransportError:
                # A transient network blip (disconnect, read timeout) mid-batch must not lose the
                # ~1000 snapshots already gathered — skip this one target and keep going. A real
                # outage skips them all, leaving events_new=0 for monitoring to catch.
                continue
            # A repo that is deleted/renamed/made-private is expected attrition — skip it too.
            # Systemic HTTP errors (403 rate-limit, 5xx) still raise and fail the run.
            if resp.status_code in (404, 451):
                continue
            resp.raise_for_status()
            drafts.append(self._snapshot_draft(resp.json()))
        return drafts

    @staticmethod
    def _discovery_draft(repo: dict[str, Any]) -> RawEventDraft:
        occurred = datetime.fromisoformat(repo["created_at"].replace("Z", "+00:00")).astimezone(UTC)
        return RawEventDraft(
            source="github",
            source_event_uid=f"repo_discovered:{repo['id']}",
            event_type="repo_discovered",
            occurred_at=occurred,
            payload=repo,
        )

    @staticmethod
    def _snapshot_draft(repo: dict[str, Any]) -> RawEventDraft:
        occurred = datetime.now(UTC)
        return RawEventDraft(
            source="github",
            source_event_uid=RawEventDraft.snapshot_uid(f"repo:{repo['id']}", occurred),
            event_type="repo_snapshot",
            occurred_at=occurred,
            payload={
                "id": repo["id"],
                "full_name": repo.get("full_name"),
                "stars": repo.get("stargazers_count"),
                "forks": repo.get("forks_count"),
                "subscribers": repo.get("subscribers_count"),
                "open_issues": repo.get("open_issues_count"),
            },
        )
