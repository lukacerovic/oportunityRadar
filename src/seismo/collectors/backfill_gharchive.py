"""GH Archive backfill (doc 03 Stage 1 item; feeds hindcast per doc 11 §1).

Writes ordinary ``raw_events`` rows flagged ``origin='backfill'`` with historical
``occurred_at`` — first-class citizens of the as-of discipline (doc 02 §5). The pure
``filter_events`` function is unit-tested; ``backfill`` streams the hourly archives.

WatchEvent ≈ the star stream → reconstruct ``repo_star`` events; ``CreateEvent`` (repository)
→ ``repo_discovered``. Scoped by target orgs/repos so a month is tractable, not the firehose.
"""

from __future__ import annotations

import gzip
import json
from collections.abc import Iterable, Iterator
from datetime import UTC, datetime, timedelta
from typing import Any

import httpx

from seismo.collectors.base import RawEventDraft, Window
from seismo.collectors.http import make_client
from seismo.collectors.runner import persist_drafts
from seismo.db import session_scope

ARCHIVE_URL = (
    "https://data.gharchive.org/{stamp}.json.gz"  # stamp = YYYY-MM-DD-H (H not zero-padded)
)


def hourly_stamps(window: Window) -> list[str]:
    stamps: list[str] = []
    cur = window.since.astimezone(UTC).replace(minute=0, second=0, microsecond=0)
    end = window.until.astimezone(UTC)
    while cur < end:
        stamps.append(f"{cur.year:04d}-{cur.month:02d}-{cur.day:02d}-{cur.hour}")
        cur = cur + timedelta(hours=1)
    return stamps


def _repo_matches(repo_name: str, targets: set[str]) -> bool:
    """``repo_name`` is 'owner/name'. Match on exact repo or owner-org membership."""
    owner = repo_name.split("/", 1)[0]
    return repo_name in targets or owner in targets


def filter_events(records: Iterable[dict[str, Any]], targets: set[str]) -> list[RawEventDraft]:
    """Pure: turn GH Archive event records into backfill drafts for target repos/orgs."""
    drafts: list[RawEventDraft] = []
    for rec in records:
        repo_name = (rec.get("repo") or {}).get("name", "")
        if not repo_name or not _repo_matches(repo_name, targets):
            continue
        etype = rec.get("type")
        created = rec.get("created_at")
        if not created:
            continue
        occurred = datetime.fromisoformat(created.replace("Z", "+00:00")).astimezone(UTC)
        if etype == "WatchEvent":
            drafts.append(
                RawEventDraft(
                    source="github",
                    source_event_uid=f"star:{repo_name}:{rec.get('id', occurred.timestamp())}",
                    event_type="repo_star",
                    occurred_at=occurred,
                    payload={"repo": repo_name, "actor": (rec.get("actor") or {}).get("login")},
                    origin="backfill",
                )
            )
        elif etype == "CreateEvent" and (rec.get("payload") or {}).get("ref_type") == "repository":
            drafts.append(
                RawEventDraft(
                    source="github",
                    source_event_uid=f"repo_discovered:{repo_name}",
                    event_type="repo_discovered",
                    occurred_at=occurred,
                    payload={"repo": repo_name, "backfilled": True},
                    origin="backfill",
                )
            )
    return drafts


def _stream_hour(client: httpx.Client, stamp: str) -> Iterator[dict[str, Any]]:
    with client.stream("GET", ARCHIVE_URL.format(stamp=stamp)) as resp:
        resp.raise_for_status()
        raw = gzip.decompress(resp.read())
    for line in raw.splitlines():
        if line:
            yield json.loads(line)


def backfill(window: Window, targets: set[str], *, client: httpx.Client | None = None) -> int:
    """Download the window's hourly archives, filter to targets, persist. Returns rows inserted."""
    owns = client is None
    client = client or make_client(timeout=120.0)
    total = 0
    try:
        for stamp in hourly_stamps(window):
            drafts = filter_events(_stream_hour(client, stamp), targets)
            with session_scope() as session:
                total += persist_drafts(session, drafts)
    finally:
        if owns:
            client.close()
    return total
