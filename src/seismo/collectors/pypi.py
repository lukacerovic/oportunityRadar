"""PyPI via pypistats + the JSON metadata API (doc 03). Usage evidence (distribution).

``track`` re-observes each known package's rolling 7-day download count (``pypi_downloads_7d``,
a *level* — the source already rolls it, never diff it as a counter) as a ``pypi_snapshot``.
``metadata`` is enrichment-only (like ``github.readmes``): it records each package's
``requires_dist``/``project_urls``/``summary`` so a later port step can build typed graph edges
from the dependency list.

PyPI has no natural "trending" feed, so ``discover`` returns nothing — new pypi anchors arrive
via seeds and via other collectors' reference-rules (an arXiv/GitHub payload that points at a
package). Both fetches are unauthenticated (the public APIs work without a token).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import Any

import httpx

from seismo.collectors.base import RateLimiter, RawEventDraft, TrackTarget, Window
from seismo.collectors.http import make_client

RECENT_URL = "https://pypistats.org/api/packages/{name}/recent"
METADATA_URL = "https://pypi.org/pypi/{name}/json"


class PyPICollector:
    source = "pypi"

    def __init__(
        self,
        *,
        client: httpx.Client | None = None,
        min_interval_s: float = 1.0,
    ):
        self._client = client or make_client()
        self._limiter = RateLimiter(min_interval_s)

    def discover(self, window: Window) -> list[RawEventDraft]:
        # PyPI has no trending endpoint suited to window-based discovery (unlike GitHub search) —
        # new pypi anchors arrive via seeds and other collectors' reference-rules. Nothing to add.
        return []

    def track(self, targets: list[TrackTarget], window: Window) -> list[RawEventDraft]:
        """Re-observe each known package's rolling 7-day downloads as a ``pypi_snapshot`` (level).

        Errors are isolated per target exactly like ``github.track``: a package with no stats yet
        (404) or a transient disconnect skips that one target, never the batch."""
        drafts: list[RawEventDraft] = []
        for target in targets:
            self._limiter.wait()
            name = target.native_id
            try:
                resp = self._client.get(RECENT_URL.format(name=name))
            except httpx.TransportError:
                continue
            if resp.status_code == 404:
                continue  # no stats for this package (yet) — expected attrition
            resp.raise_for_status()
            drafts.append(self._snapshot_draft(name, resp.json()))
        return drafts

    def metadata(self, targets: list[TrackTarget]) -> list[RawEventDraft]:
        """Fetch each package's PyPI JSON metadata as a ``pypi_metadata`` enrichment event.

        Records ``requires_dist`` (the dependency list a later step turns into typed graph edges),
        ``project_urls`` and ``summary``. Enrichment-only — not part of the ``BaseCollector``
        protocol (like ``github.readmes``). Errors isolated per target: a deleted package (404) or
        a transient disconnect skips that one target. Idempotent — one event per package name."""
        drafts: list[RawEventDraft] = []
        for target in targets:
            self._limiter.wait()
            name = target.native_id
            try:
                resp = self._client.get(METADATA_URL.format(name=name))
            except httpx.TransportError:
                continue
            if resp.status_code == 404:
                continue  # package gone — expected attrition
            resp.raise_for_status()
            drafts.append(self._metadata_draft(name, resp.json()))
        return drafts

    @staticmethod
    def _snapshot_draft(name: str, data: dict[str, Any]) -> RawEventDraft:
        occurred = datetime.now(UTC)
        return RawEventDraft(
            source="pypi",
            source_event_uid=RawEventDraft.snapshot_uid(f"pypi:{name}", occurred),
            event_type="pypi_snapshot",
            occurred_at=occurred,
            payload={"name": name, "downloads_7d": data["data"]["last_week"]},
        )

    @staticmethod
    def _metadata_draft(name: str, data: dict[str, Any]) -> RawEventDraft:
        info: dict[str, Any] = data.get("info") or {}
        return RawEventDraft(
            source="pypi",
            source_event_uid=f"pypi_metadata:{name}",
            event_type="pypi_metadata",
            occurred_at=datetime.now(UTC),
            payload={
                "name": name,
                "requires_dist": info.get("requires_dist") or [],
                "project_urls": info.get("project_urls") or {},
                "summary": info.get("summary"),
            },
        )
