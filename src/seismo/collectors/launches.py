"""Launch-page enrichment for HN-native launches (Wave-3).

A ``web``-anchored entity (e.g. Kimi) is born from an HN story that links to no tracked registry,
so all it carries is a headline. This fetches the launch page behind that story and stores its
readable text as a ``launch_page`` event — the same role ``repo_readme`` plays for GitHub repos
(§16): it gives the comprehension checkpoint real substance instead of a one-line title.

Best-effort by design: many launch URLs are JS-only, paywalled, or auth-gated (x.com), so a fetch
that yields too little text is skipped rather than stored. Errors are isolated per target.
"""

from __future__ import annotations

import re
from datetime import UTC, datetime
from html.parser import HTMLParser

import httpx
from pydantic import BaseModel
from sqlalchemy import text
from sqlalchemy.orm import Session

from seismo.collectors.base import RateLimiter, RawEventDraft
from seismo.collectors.http import make_client

_TEXT_CAP = 4000  # matches resolve._TEXT_CAP — the entity keeps a 4k text sample
_MIN_USABLE = 80  # fewer chars than this ⇒ JS-only / paywalled page, not worth storing


class LaunchTarget(BaseModel):
    entity_id: int
    slug: str
    name: str
    url: str


class HnTarget(BaseModel):
    entity_id: int
    name: str
    anchor_registry: str
    anchor_native_id: str
    story_id: str
    url: str | None
    points: int


# Priority for picking one existing anchor to route the enrichment back through.
_ANCHOR_PRIORITY = ("hf", "github", "arxiv", "web", "pypi", "npm")


class _TextExtractor(HTMLParser):
    """Collect visible text, skipping non-content elements. Stdlib only (no bs4 dependency)."""

    _SKIP = {"script", "style", "noscript", "head", "svg", "template", "nav", "footer"}

    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self._chunks: list[str] = []
        self._skip_depth = 0

    def handle_starttag(self, tag: str, attrs: object) -> None:
        if tag in self._SKIP:
            self._skip_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if tag in self._SKIP and self._skip_depth:
            self._skip_depth -= 1

    def handle_data(self, data: str) -> None:
        if self._skip_depth == 0:
            chunk = data.strip()
            if chunk:
                self._chunks.append(chunk)

    def text(self) -> str:
        return " ".join(self._chunks)


def html_to_text(html: str, cap: int = _TEXT_CAP) -> str:
    """Extract readable text from an HTML document, collapsed and capped."""
    parser = _TextExtractor()
    try:
        parser.feed(html)
    except Exception:  # noqa: BLE001 — a malformed page shouldn't abort the batch
        pass
    return re.sub(r"\s+", " ", parser.text()).strip()[:cap]


def select_launch_targets(session: Session, *, limit: int | None = None) -> list[LaunchTarget]:
    """Web-anchored launches that still lack a ``launch_page`` event, with the HN story URL to
    fetch (highest-scoring story wins when a launch was posted more than once)."""
    rows = session.execute(
        text(
            """
            SELECT e.id AS entity_id,
                   e.attrs->'anchors'->>'web' AS slug,
                   e.canonical_name AS name,
                   (SELECT re.payload->>'url' FROM entity_links l
                    JOIN raw_events re ON re.id = l.raw_event_id
                    WHERE l.entity_id = e.id AND re.source = 'hn'
                      AND re.payload->>'url' IS NOT NULL AND re.payload->>'url' <> ''
                    ORDER BY (re.payload->>'points')::int DESC NULLS LAST
                    LIMIT 1) AS url
            FROM entities e
            WHERE e.attrs->'anchors' ? 'web' AND e.merged_into IS NULL
              AND NOT EXISTS (
                SELECT 1 FROM entity_links l2 JOIN raw_events r2 ON r2.id = l2.raw_event_id
                WHERE l2.entity_id = e.id AND r2.event_type = 'launch_page')
            ORDER BY e.id
            """
            + ("LIMIT :limit" if limit else "")
        ),
        {"limit": limit} if limit else {},
    ).mappings()
    return [
        LaunchTarget(entity_id=r["entity_id"], slug=r["slug"], name=r["name"], url=r["url"])
        for r in rows
        if r["url"] and r["slug"]
    ]


class LaunchEnricher:
    """Fetches launch pages and drafts ``launch_page`` events (source ``web``)."""

    def __init__(self, *, client: httpx.Client | None = None, min_interval_s: float = 0.5):
        self._client = client or make_client()
        self._limiter = RateLimiter(min_interval_s)

    def fetch(self, targets: list[LaunchTarget]) -> list[RawEventDraft]:
        drafts: list[RawEventDraft] = []
        for t in targets:
            self._limiter.wait()
            try:
                resp = self._client.get(t.url)
            except httpx.HTTPError:
                continue  # DNS/timeout/redirect loop — skip this one, keep the batch going
            if resp.status_code >= 400:
                continue
            ctype = resp.headers.get("content-type", "").lower()
            if "html" not in ctype and "text" not in ctype:
                continue  # a PDF/image/binary launch link — nothing to read
            body = html_to_text(resp.text)
            if len(body) < _MIN_USABLE:
                continue  # JS-only / paywalled — no usable text to card from
            drafts.append(self._draft(t, body))
        return drafts

    @staticmethod
    def _draft(target: LaunchTarget, body: str) -> RawEventDraft:
        # Enrichment, not discovery: occurred_at = now. The ``web`` anchor + slug route it back to
        # the launch entity in resolve; one event per launch (idempotent on the uid).
        return RawEventDraft(
            source="web",
            source_event_uid=f"launch_page:{target.slug}",
            event_type="launch_page",
            occurred_at=datetime.now(UTC),
            payload={"slug": target.slug, "name": target.name, "url": target.url, "text": body},
        )


def select_hn_targets(
    session: Session, *, min_points: int = 100, limit: int | None = None
) -> list[HnTarget]:
    """Entities carrying a high-signal HN story whose *discussion* we haven't captured yet. Routes
    the enrichment through one of the entity's existing anchors so it attaches precisely."""
    rows = session.execute(
        text(
            """
            SELECT e.id AS entity_id, e.canonical_name AS name, e.attrs->'anchors' AS anchors,
                   hn.story_id, hn.url, hn.points
            FROM entities e
            JOIN LATERAL (
                SELECT re.payload->>'objectID' AS story_id, re.payload->>'url' AS url,
                       COALESCE((re.payload->>'points')::int, 0) AS points
                FROM entity_links l JOIN raw_events re ON re.id = l.raw_event_id
                WHERE l.entity_id = e.id AND re.source = 'hn' AND re.event_type = 'story'
                  AND re.payload->>'objectID' IS NOT NULL
                ORDER BY COALESCE((re.payload->>'points')::int, 0) DESC
                LIMIT 1
            ) hn ON true
            WHERE e.merged_into IS NULL AND hn.points >= :floor
              AND e.attrs->'anchors' <> '{}'::jsonb
              AND NOT EXISTS (
                SELECT 1 FROM entity_links l2 JOIN raw_events r2 ON r2.id = l2.raw_event_id
                WHERE l2.entity_id = e.id AND r2.event_type = 'hn_discussion')
            ORDER BY hn.points DESC
            """
            + ("LIMIT :limit" if limit else ""),
        ),
        {"floor": min_points, **({"limit": limit} if limit else {})},
    ).mappings()

    targets: list[HnTarget] = []
    for r in rows:
        anchors = r["anchors"] or {}
        reg = next((k for k in _ANCHOR_PRIORITY if k in anchors), None)
        if not reg:
            continue
        targets.append(
            HnTarget(
                entity_id=r["entity_id"],
                name=r["name"],
                anchor_registry=reg,
                anchor_native_id=str(anchors[reg]),
                story_id=r["story_id"],
                url=r["url"],
                points=r["points"],
            )
        )
    return targets


def _top_comments(item: dict, limit: int = 12) -> list[str]:
    """Readable text of the top-level comments on an HN story (the substantive discussion)."""
    out: list[str] = []
    for child in item.get("children") or []:
        raw = child.get("text")
        if raw:
            clean = html_to_text(raw, cap=600)
            if len(clean) >= 40:
                out.append(clean)
        if len(out) >= limit:
            break
    return out


class HnDiscussionEnricher:
    """Fetches the discussion under an HN story and drafts an ``hn_discussion`` enrichment event."""

    ITEM_URL = "https://hn.algolia.com/api/v1/items/{id}"

    def __init__(self, *, client: httpx.Client | None = None, min_interval_s: float = 0.3):
        self._client = client or make_client()
        self._limiter = RateLimiter(min_interval_s)

    def fetch(self, targets: list[HnTarget]) -> list[RawEventDraft]:
        drafts: list[RawEventDraft] = []
        for t in targets:
            self._limiter.wait()
            try:
                resp = self._client.get(self.ITEM_URL.format(id=t.story_id))
            except httpx.HTTPError:
                continue
            if resp.status_code >= 400:
                continue
            comments = _top_comments(resp.json() or {})
            if not comments:
                continue
            body = "\n\n".join(comments)[: _TEXT_CAP * 2]
            drafts.append(
                RawEventDraft(
                    source="enrich",
                    source_event_uid=f"hn_discussion:{t.story_id}",
                    event_type="hn_discussion",
                    occurred_at=datetime.now(UTC),
                    payload={
                        "anchor": {"registry": t.anchor_registry, "native_id": t.anchor_native_id},
                        "name": t.name,
                        "url": t.url,
                        "story_id": t.story_id,
                        "text": body,
                    },
                )
            )
        return drafts
