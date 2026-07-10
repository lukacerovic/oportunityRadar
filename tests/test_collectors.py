"""Collector parsing (mocked HTTP) and the framework's idempotence + failure isolation."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import httpx

from seismo.collectors.arxiv import ArxivCollector
from seismo.collectors.backfill_gharchive import filter_events, hourly_stamps
from seismo.collectors.base import RawEventDraft, Window
from seismo.collectors.hn import HackerNewsCollector
from seismo.collectors.runner import persist_drafts, run_collector

NOW = datetime(2026, 7, 1, 12, 0, tzinfo=UTC)
WINDOW = Window(since=NOW - timedelta(days=2), until=NOW)


def _client(handler) -> httpx.Client:
    return httpx.Client(transport=httpx.MockTransport(handler))


# --- HN parsing -------------------------------------------------------------


def test_hn_captures_by_url_and_points_and_keyword() -> None:
    hits = [
        {
            "objectID": "1",
            "title": "random",
            "url": "https://github.com/x/y",
            "points": 3,
            "created_at_i": int((NOW - timedelta(days=1)).timestamp()),
        },
        {
            "objectID": "2",
            "title": "cool tool",
            "url": "https://example.com",
            "points": 120,
            "created_at_i": int((NOW - timedelta(days=1)).timestamp()),
        },
        {
            "objectID": "3",
            "title": "a new LLM agent",
            "url": "https://blog.example.com",
            "points": 4,
            "created_at_i": int((NOW - timedelta(days=1)).timestamp()),
        },
        {
            "objectID": "4",
            "title": "cooking recipe",
            "url": "https://food.example.com",
            "points": 2,
            "created_at_i": int((NOW - timedelta(days=1)).timestamp()),
        },
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"hits": hits, "nbPages": 1})

    drafts = HackerNewsCollector(client=_client(handler), min_interval_s=0).discover(WINDOW)
    captured = {d.source_event_uid for d in drafts}
    assert captured == {"1", "2", "3"}  # github url, high points, keyword — not the recipe
    assert all(d.source == "hn" and d.event_type == "story" for d in drafts)


# --- arXiv parsing ----------------------------------------------------------

_ATOM_FEED = """<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns="http://www.w3.org/2005/Atom" xmlns:arxiv="http://arxiv.org/schemas/atom">
  <entry>
    <id>http://arxiv.org/abs/2405.04434v1</id>
    <title>DeepSeek-V2</title>
    <summary>A strong MoE model.</summary>
    <published>2026-06-30T00:00:00Z</published>
    <author><name>Jane Doe</name></author>
    <arxiv:comment>Code at https://github.com/deepseek-ai/DeepSeek-V2</arxiv:comment>
    <category term="cs.CL"/>
  </entry>
</feed>"""


def test_arxiv_parses_id_comment_and_window() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        # Second page returns empty so the loop terminates.
        start = int(request.url.params.get("start", "0"))
        return httpx.Response(
            200,
            text=_ATOM_FEED if start == 0 else "<feed xmlns='http://www.w3.org/2005/Atom'></feed>",
        )

    win = Window(since=datetime(2026, 6, 29, tzinfo=UTC), until=datetime(2026, 7, 1, tzinfo=UTC))
    drafts = ArxivCollector(client=_client(handler), min_interval_s=0).discover(win)
    assert len(drafts) == 1
    d = drafts[0]
    assert d.source_event_uid == "2405.04434"
    assert "github.com/deepseek-ai" in d.payload["comment"]


# --- backfill filter (pure) -------------------------------------------------


def test_gharchive_filter_matches_org_and_repo() -> None:
    records = [
        {
            "type": "WatchEvent",
            "id": "9",
            "repo": {"name": "deepseek-ai/DeepSeek-V2"},
            "actor": {"login": "a"},
            "created_at": "2024-05-10T00:00:00Z",
        },
        {
            "type": "CreateEvent",
            "repo": {"name": "deepseek-ai/other"},
            "payload": {"ref_type": "repository"},
            "created_at": "2024-05-10T00:00:00Z",
        },
        {
            "type": "WatchEvent",
            "id": "7",
            "repo": {"name": "someone/unrelated"},
            "created_at": "2024-05-10T00:00:00Z",
        },
    ]
    drafts = filter_events(records, {"deepseek-ai"})
    kinds = sorted(d.event_type for d in drafts)
    assert kinds == ["repo_discovered", "repo_star"]
    assert all(d.origin == "backfill" for d in drafts)


def test_hourly_stamps_span_day_boundary() -> None:
    win = Window(
        since=datetime(2024, 5, 10, 23, tzinfo=UTC), until=datetime(2024, 5, 11, 1, tzinfo=UTC)
    )
    assert hourly_stamps(win) == ["2024-05-10-23", "2024-05-11-0"]


# --- framework: idempotence & isolation -------------------------------------


class _FakeCollector:
    source = "test_fake"

    def __init__(self, drafts: list[RawEventDraft], *, boom: bool = False):
        self._drafts = drafts
        self._boom = boom

    def discover(self, window: Window) -> list[RawEventDraft]:
        if self._boom:
            raise RuntimeError("upstream 500")
        return self._drafts

    def track(self, targets, window):  # noqa: ANN001
        return []


def _draft(uid: str) -> RawEventDraft:
    return RawEventDraft(
        source="test_fake", source_event_uid=uid, event_type="t", occurred_at=NOW, payload={}
    )


def test_persist_is_idempotent(db_session) -> None:  # noqa: ANN001
    drafts = [_draft("a"), _draft("b")]
    assert persist_drafts(db_session, drafts) == 2
    db_session.flush()
    assert persist_drafts(db_session, drafts) == 0  # re-run inserts zero duplicates


def test_run_collector_records_health_and_dedupes(db_session) -> None:  # noqa: ANN001
    collector = _FakeCollector([_draft("x"), _draft("y")])
    first = run_collector(collector, WINDOW, session=db_session)
    db_session.flush()
    second = run_collector(collector, WINDOW, session=db_session)
    assert first.ok and first.events_new == 2
    assert second.ok and second.events_new == 0


def test_failure_is_isolated(db_session) -> None:  # noqa: ANN001
    result = run_collector(_FakeCollector([], boom=True), WINDOW, session=db_session)
    assert result.ok is False
    assert "upstream 500" in (result.error or "")
