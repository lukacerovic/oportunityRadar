"""arXiv via the export API (Atom), doc 03 §2.3. Categories per doc 13 A-9. Politeness ~1 req/3s.

Capability-claim evidence. The ``comment`` field often carries the GitHub link — gold for
identity (doc 04 R2).
"""

from __future__ import annotations

import xml.etree.ElementTree as ET
from datetime import UTC, datetime
from typing import Any

import httpx

from seismo.collectors.base import RateLimiter, RawEventDraft, TrackTarget, Window
from seismo.collectors.http import make_client

BASE = "https://export.arxiv.org/api/query"
CATEGORIES = [
    "cs.AI",
    "cs.CL",
    "cs.LG",
    "cs.SE",
    "cs.IR",
    "stat.ML",
    "cs.CR",
    "cs.MA",
    "cs.CV",
    "cs.DC",
]
PAGE_SIZE = 100
MAX_PAGES = 20

_ATOM = "{http://www.w3.org/2005/Atom}"
_ARXIV = "{http://arxiv.org/schemas/atom}"


class ArxivCollector:
    source = "arxiv"

    def __init__(self, *, client: httpx.Client | None = None, min_interval_s: float = 3.0):
        self._client = client or make_client()
        self._limiter = RateLimiter(min_interval_s)

    def discover(self, window: Window) -> list[RawEventDraft]:
        # arXiv uses '+' as an encoded space between terms; pass real spaces and let httpx
        # encode them (passing a literal '+' would be re-encoded to %2B and break the query).
        query = " OR ".join(f"cat:{c}" for c in CATEGORIES)
        drafts: list[RawEventDraft] = []
        for page in range(MAX_PAGES):
            self._limiter.wait()
            params: dict[str, str | int] = {
                "search_query": query,
                "sortBy": "submittedDate",
                "sortOrder": "descending",
                "start": page * PAGE_SIZE,
                "max_results": PAGE_SIZE,
            }
            resp = self._client.get(BASE, params=params)
            resp.raise_for_status()
            entries = self._parse(resp.text)
            if not entries:
                break
            stop = False
            for occurred, draft in entries:
                if occurred < window.since:
                    stop = True  # sorted desc — everything after is older
                    continue
                if occurred < window.until:
                    drafts.append(draft)
            if stop:
                break
        return drafts

    def track(self, targets: list[TrackTarget], window: Window) -> list[RawEventDraft]:
        # citation velocity (Semantic Scholar) is a Wave-3 add; discovery only in v1.
        return []

    def fetch_ids(self, arxiv_ids: list[str]) -> list[RawEventDraft]:
        """Targeted fetch of specific papers by id — the hindcast seed path (doc 11 §1).

        ``discover`` pages from the newest submissions and so cannot reach an arbitrary historical
        window; a case, however, pins exact ids, so we jump straight to them via ``id_list``. The
        returned ``paper_published`` events carry their real ``published`` date, so replay places
        them in history correctly. Version suffixes are stripped by ``_parse`` (id → bare id)."""
        if not arxiv_ids:
            return []
        self._limiter.wait()
        params: dict[str, str | int] = {
            "id_list": ",".join(arxiv_ids),
            "max_results": len(arxiv_ids),
        }
        resp = self._client.get(BASE, params=params)
        resp.raise_for_status()
        return [draft for _occurred, draft in self._parse(resp.text)]

    def _parse(self, xml_text: str) -> list[tuple[datetime, RawEventDraft]]:
        root = ET.fromstring(xml_text)
        out: list[tuple[datetime, RawEventDraft]] = []
        for entry in root.findall(f"{_ATOM}entry"):
            id_url = (entry.findtext(f"{_ATOM}id") or "").strip()
            arxiv_id = id_url.rsplit("/abs/", 1)[-1] if "/abs/" in id_url else id_url
            bare_id = arxiv_id.split("v")[0] if arxiv_id else ""
            published_text = (entry.findtext(f"{_ATOM}published") or "").strip()
            if not bare_id or not published_text:
                continue
            occurred = datetime.fromisoformat(published_text.replace("Z", "+00:00")).astimezone(UTC)
            payload: dict[str, Any] = {
                "arxiv_id": bare_id,
                "version_id": arxiv_id,
                "title": (entry.findtext(f"{_ATOM}title") or "").strip(),
                "summary": (entry.findtext(f"{_ATOM}summary") or "").strip(),
                "comment": (entry.findtext(f"{_ARXIV}comment") or "").strip(),
                "authors": [
                    (a.findtext(f"{_ATOM}name") or "").strip()
                    for a in entry.findall(f"{_ATOM}author")
                ],
                "categories": [c.attrib.get("term", "") for c in entry.findall(f"{_ATOM}category")],
            }
            draft = RawEventDraft(
                source="arxiv",
                source_event_uid=bare_id,
                event_type="paper_published",
                occurred_at=occurred,
                payload=payload,
            )
            out.append((occurred, draft))
        return out
