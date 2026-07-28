"""GitHub community client — the entity's *own* community feedback.

Reads the repo's **Issues** (REST, works unauthenticated at 60 req/hr) and **Discussions**
(GraphQL, requires a token — skipped gracefully when none is set). This is disjoint from
``collectors.github``, which only reads repo metadata, star/fork snapshots, and the README — it
never touches issues or discussions. Highest-precision opinion signal: every thread is on the
exact repo, so there is no name-disambiguation problem. Pull requests are intentionally excluded
(they are contributions, not opinion).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import httpx

from seismo.collectors.base import RateLimiter
from seismo.collectors.http import make_client
from seismo.community.relevance import CommunityThread, _int
from seismo.community.targets import CommunityTarget
from seismo.config import settings

API = "https://api.github.com"
GRAPHQL = "https://api.github.com/graphql"
ACCEPT = "application/vnd.github+json"
BODY_CAP = 2000  # only used for relevance scoring; never persisted

_DISCUSSIONS_Q = """
query($owner:String!, $repo:String!, $n:Int!) {
  repository(owner:$owner, name:$repo) {
    discussions(first:$n, orderBy:{field:UPDATED_AT, direction:DESC}) {
      nodes { number title url createdAt bodyText category{name} comments{totalCount} }
    }
  }
}
"""

_DISCUSSION_COMMENTS_Q = """
query($owner:String!, $repo:String!, $number:Int!, $n:Int!) {
  repository(owner:$owner, name:$repo) {
    discussion(number:$number) { comments(first:$n) { nodes { bodyText } } }
  }
}
"""


class GitHubCommunityClient:
    source = "github"

    def __init__(
        self,
        *,
        token: str | None = None,
        client: httpx.Client | None = None,
        min_interval_s: float = 1.0,
    ):
        self._token = token if token is not None else (settings.github_token or None)
        self._client = client or make_client()
        self._limiter = RateLimiter(min_interval_s)

    def applies_to(self, target: CommunityTarget) -> bool:
        return bool(_owner_repo(target))

    def fetch_threads(
        self, target: CommunityTarget, queries: list[str], *, limit: int
    ) -> list[CommunityThread]:
        owner_repo = _owner_repo(target)
        if owner_repo is None:
            return []
        owner, repo = owner_repo
        threads = self._issues(owner, repo, limit)
        if self._token:  # Discussions are GraphQL-only, which requires auth.
            threads.extend(self._discussions(owner, repo, limit))
        return threads

    def comments(self, thread: CommunityThread, *, limit: int) -> list[str]:
        ref = thread.ref or {}
        if ref.get("kind") == "issue":
            return self._issue_comments(ref["owner"], ref["repo"], int(ref["number"]), limit)
        if ref.get("kind") == "discussion":
            return self._discussion_comments(ref["owner"], ref["repo"], int(ref["number"]), limit)
        return []

    def close(self) -> None:
        self._client.close()

    # --- issues (REST) ------------------------------------------------------
    def _issues(self, owner: str, repo: str, limit: int) -> list[CommunityThread]:
        self._limiter.wait()
        try:
            resp = self._client.get(
                f"{API}/repos/{owner}/{repo}/issues",
                params={
                    "state": "all",
                    "sort": "comments",
                    "direction": "desc",
                    "per_page": limit,
                },
                headers=self._headers(),
            )
        except httpx.TransportError:
            return []
        if resp.status_code in (404, 451):
            return []  # repo gone / DMCA'd — expected attrition
        resp.raise_for_status()
        out: list[CommunityThread] = []
        for item in resp.json():
            if "pull_request" in item:  # PRs are contributions, not opinion
                continue
            out.append(self._issue_thread(owner, repo, item))
        return out

    def _issue_comments(self, owner: str, repo: str, number: int, limit: int) -> list[str]:
        self._limiter.wait()
        try:
            resp = self._client.get(
                f"{API}/repos/{owner}/{repo}/issues/{number}/comments",
                params={"per_page": limit},
                headers=self._headers(),
            )
        except httpx.TransportError:
            return []
        if resp.status_code >= 400:
            return []
        bodies = [(c.get("body") or "").strip() for c in resp.json()]
        return [b for b in bodies if b][:limit]

    @staticmethod
    def _issue_thread(owner: str, repo: str, item: dict[str, Any]) -> CommunityThread:
        number = int(item["number"])
        return CommunityThread(
            thread_id=f"issue:{owner}/{repo}#{number}",
            title=str(item.get("title") or ""),
            source="github",
            channel="GitHub Issues",
            url=str(item.get("html_url") or ""),
            score=_int((item.get("reactions") or {}).get("total_count")),
            comment_count=_int(item.get("comments")),
            created_at=_ts(item.get("created_at")),
            body=(item.get("body") or "")[:BODY_CAP] or None,
            matched_queries=[f"repo:{owner}/{repo} issues"],
            ref={"kind": "issue", "owner": owner, "repo": repo, "number": number},
        )

    # --- discussions (GraphQL) ---------------------------------------------
    def _discussions(self, owner: str, repo: str, limit: int) -> list[CommunityThread]:
        data = self._graphql(_DISCUSSIONS_Q, {"owner": owner, "repo": repo, "n": limit})
        repo_node = (((data or {}).get("data") or {}).get("repository")) or {}
        nodes = ((repo_node.get("discussions") or {}).get("nodes")) or []
        out: list[CommunityThread] = []
        for node in nodes:
            number = int(node["number"])
            out.append(
                CommunityThread(
                    thread_id=f"discussion:{owner}/{repo}#{number}",
                    title=str(node.get("title") or ""),
                    source="github",
                    channel="GitHub Discussions",
                    url=str(node.get("url") or ""),
                    comment_count=_int((node.get("comments") or {}).get("totalCount")),
                    created_at=_ts(node.get("createdAt")),
                    body=(node.get("bodyText") or "")[:BODY_CAP] or None,
                    matched_queries=[f"repo:{owner}/{repo} discussions"],
                    ref={"kind": "discussion", "owner": owner, "repo": repo, "number": number},
                )
            )
        return out

    def _discussion_comments(self, owner: str, repo: str, number: int, limit: int) -> list[str]:
        data = self._graphql(
            _DISCUSSION_COMMENTS_Q, {"owner": owner, "repo": repo, "number": number, "n": limit}
        )
        discussion = (((data or {}).get("data") or {}).get("repository") or {}).get("discussion")
        nodes = ((discussion or {}).get("comments") or {}).get("nodes") or []
        bodies = [(n.get("bodyText") or "").strip() for n in nodes]
        return [b for b in bodies if b][:limit]

    def _graphql(self, query: str, variables: dict[str, Any]) -> dict[str, Any] | None:
        if not self._token:
            return None
        self._limiter.wait()
        try:
            resp = self._client.post(
                GRAPHQL,
                json={"query": query, "variables": variables},
                headers=self._headers(),
            )
        except httpx.TransportError:
            return None
        if resp.status_code >= 400:
            return None
        return resp.json()

    def _headers(self) -> dict[str, str]:
        headers = {"Accept": ACCEPT}
        if self._token:
            headers["Authorization"] = f"Bearer {self._token}"
        return headers


def _owner_repo(target: CommunityTarget) -> tuple[str, str] | None:
    gh = target.anchors.get("github")
    if not gh or "/" not in gh:
        return None
    owner, _, repo = gh.partition("/")
    owner, repo = owner.strip(), repo.strip()
    return (owner, repo) if owner and repo else None


def _ts(raw: str | None) -> datetime | None:
    if not raw:
        return None
    try:
        return datetime.fromisoformat(str(raw).replace("Z", "+00:00")).astimezone(UTC)
    except ValueError:
        return None
