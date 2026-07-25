"""Collector parsing (mocked HTTP) and the framework's idempotence + failure isolation."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import httpx

from seismo.collectors.arxiv import ArxivCollector
from seismo.collectors.backfill_gharchive import filter_events, hourly_stamps
from seismo.collectors.base import RawEventDraft, TrackTarget, Window
from seismo.collectors.github import GitHubCollector
from seismo.collectors.hf import HuggingFaceCollector
from seismo.collectors.hn import HackerNewsCollector
from seismo.collectors.openrouter import OpenRouterCollector
from seismo.collectors.pypi import PyPICollector
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


# --- GitHub tracking (per-target failure isolation) -------------------------


def test_github_track_skips_deleted_repos() -> None:
    """A 404 (deleted/renamed/private repo) must skip that target, not abort the batch."""

    def handler(request: httpx.Request) -> httpx.Response:
        if "gone/repo" in str(request.url):
            return httpx.Response(404, json={"message": "Not Found"})
        return httpx.Response(
            200,
            json={"id": 7, "full_name": "live/repo", "stargazers_count": 50, "forks_count": 5},
        )

    targets = [
        TrackTarget(entity_id=1, source="github", native_id="gone/repo"),
        TrackTarget(entity_id=2, source="github", native_id="live/repo"),
    ]
    drafts = GitHubCollector(client=_client(handler), min_interval_s=0, token="x").track(
        targets, WINDOW
    )
    assert len(drafts) == 1, "the live repo still produces a snapshot despite the dead one"
    assert drafts[0].event_type == "repo_snapshot"
    assert drafts[0].payload["stars"] == 50


def test_github_track_skips_transient_network_errors() -> None:
    """A mid-batch disconnect must skip that target, not lose the whole run's snapshots."""

    def handler(request: httpx.Request) -> httpx.Response:
        if "flaky/repo" in str(request.url):
            raise httpx.RemoteProtocolError("server disconnected")
        return httpx.Response(
            200,
            json={"id": 9, "full_name": "live/repo", "stargazers_count": 12, "forks_count": 1},
        )

    targets = [
        TrackTarget(entity_id=1, source="github", native_id="flaky/repo"),
        TrackTarget(entity_id=2, source="github", native_id="live/repo"),
    ]
    drafts = GitHubCollector(client=_client(handler), min_interval_s=0, token="x").track(
        targets, WINDOW
    )
    assert len(drafts) == 1 and drafts[0].payload["stars"] == 12


# --- GitHub README enrichment (§16) -----------------------------------------


def test_github_readmes_fetch_and_skip_missing() -> None:
    """A repo with a README yields a repo_readme event; a 404 (no README) skips that target."""

    def handler(request: httpx.Request) -> httpx.Response:
        if "no-readme/repo" in str(request.url):
            return httpx.Response(404, json={"message": "Not Found"})
        return httpx.Response(200, text="# Big Model\n\nA long, substantive README body.")

    targets = [
        TrackTarget(entity_id=1, source="github", native_id="no-readme/repo"),
        TrackTarget(entity_id=2, source="github", native_id="has/readme"),
    ]
    drafts = GitHubCollector(client=_client(handler), min_interval_s=0, token="x").readmes(
        targets, WINDOW
    )
    assert len(drafts) == 1, "the missing-README repo is skipped, the other still enriches"
    d = drafts[0]
    assert d.event_type == "repo_readme"
    assert d.source_event_uid == "repo_readme:has/readme"  # idempotent per repo
    assert d.payload["full_name"] == "has/readme"
    assert "substantive README body" in d.payload["text"]


def test_hf_model_cards_fetch_strip_frontmatter_and_skip_missing() -> None:
    """A model with a card yields model_readme (YAML frontmatter stripped); a 404 skips it."""

    def handler(request: httpx.Request) -> httpx.Response:
        if "gated/model" in str(request.url):
            return httpx.Response(401, text="access denied")
        return httpx.Response(
            200,
            text="---\nlicense: mit\ntags: [llm]\n---\n# Kimi\n\nA 1T-param MoE model for agents.",
        )

    targets = [
        TrackTarget(entity_id=1, source="hf", native_id="gated/model"),
        TrackTarget(entity_id=2, source="hf", native_id="acme/good-model"),
    ]
    drafts = HuggingFaceCollector(client=_client(handler), min_interval_s=0).model_cards(targets)
    assert len(drafts) == 1, "the gated model is skipped, the other still enriches"
    d = drafts[0]
    assert d.event_type == "model_readme"
    assert d.source_event_uid == "model_readme:acme/good-model"  # idempotent per model
    assert d.payload["id"] == "acme/good-model"
    assert "1T-param MoE model" in d.payload["text"]
    assert "license: mit" not in d.payload["text"], "YAML frontmatter is stripped"


def test_github_readmes_skip_transient_and_empty() -> None:
    """A mid-batch disconnect and an empty README body both skip cleanly."""

    def handler(request: httpx.Request) -> httpx.Response:
        if "flaky/repo" in str(request.url):
            raise httpx.RemoteProtocolError("server disconnected")
        if "empty/repo" in str(request.url):
            return httpx.Response(200, text="   \n  ")
        return httpx.Response(200, text="real content")

    targets = [
        TrackTarget(entity_id=1, source="github", native_id="flaky/repo"),
        TrackTarget(entity_id=2, source="github", native_id="empty/repo"),
        TrackTarget(entity_id=3, source="github", native_id="good/repo"),
    ]
    drafts = GitHubCollector(client=_client(handler), min_interval_s=0, token="x").readmes(
        targets, WINDOW
    )
    assert [d.payload["full_name"] for d in drafts] == ["good/repo"]


# --- GitHub contributors enrichment (Feature 1) -----------------------------


def test_github_contributors_fetch_and_skip_missing() -> None:
    """A repo yields a repo_contributors event (top-N logins); a 404 skips that target."""

    def handler(request: httpx.Request) -> httpx.Response:
        if "gone/repo" in str(request.url):
            return httpx.Response(404, json={"message": "Not Found"})
        return httpx.Response(
            200,
            json=[
                {"login": "alice", "contributions": 120, "id": 1},
                {"login": "bob", "contributions": 30, "id": 2},
            ],
        )

    targets = [
        TrackTarget(entity_id=1, source="github", native_id="gone/repo"),
        TrackTarget(entity_id=2, source="github", native_id="live/repo"),
    ]
    drafts = GitHubCollector(client=_client(handler), min_interval_s=0, token="x").contributors(
        targets, WINDOW
    )
    assert len(drafts) == 1, "the missing repo is skipped, the live one still enriches"
    d = drafts[0]
    assert d.event_type == "repo_contributors"
    assert d.source_event_uid == "repo_contributors:live/repo"  # idempotent per repo
    assert d.payload["full_name"] == "live/repo"
    assert d.payload["contributors"] == [
        {"login": "alice", "contributions": 120},
        {"login": "bob", "contributions": 30},
    ]


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


def test_arxiv_fetch_ids_targets_by_id_list() -> None:
    """The hindcast seed path: fetch a specific paper by id (not a windowed discover)."""

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params.get("id_list") == "2405.04434"
        return httpx.Response(200, text=_ATOM_FEED)

    drafts = ArxivCollector(client=_client(handler), min_interval_s=0).fetch_ids(["2405.04434"])
    assert len(drafts) == 1 and drafts[0].source_event_uid == "2405.04434"
    assert drafts[0].event_type == "paper_published"


def test_arxiv_fetch_ids_empty_makes_no_request() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("fetch_ids([]) must not hit the network")

    assert ArxivCollector(client=_client(handler), min_interval_s=0).fetch_ids([]) == []


# --- Hugging Face parsing ---------------------------------------------------


def _hf_model(model_id: str, created: datetime, **extra: object) -> dict:
    return {"id": model_id, "createdAt": created.isoformat().replace("+00:00", "Z"), **extra}


def test_hf_discover_filters_by_window_and_relevance_across_cursor() -> None:
    """createdAt window + relevance (traction AND modality), paginating the Link-header cursor.

    Relevance needs BOTH real traction (downloads/likes) and a relevant modality (pipeline or
    keyword) — a no-traction clone that merely inherits ``text-generation`` is noise, and a
    high-download model in an off-topic modality isn't the usage signal we track."""
    page1 = [
        # after `until` → excluded regardless of traction
        _hf_model(
            "acme/too-new", NOW + timedelta(days=1), pipeline_tag="text-generation", likes=99
        ),
        # traction + relevant pipeline → kept
        _hf_model(
            "acme/llm-chat", NOW - timedelta(days=1), pipeline_tag="text-generation", downloads=5000
        ),
        # traction but off-topic modality → dropped
        _hf_model(
            "acme/big-vision",
            NOW - timedelta(days=1),
            pipeline_tag="image-segmentation",
            downloads=9000,
        ),
        # relevant pipeline but no traction → dropped
        _hf_model(
            "acme/empty-clone", NOW - timedelta(days=1), pipeline_tag="text-generation", downloads=5
        ),
    ]
    page2 = [
        # traction (likes) + keyword in tags → kept
        _hf_model("acme/agent-tool", NOW - timedelta(hours=6), tags=["agent"], likes=40),
        # before `since` → excluded
        _hf_model(
            "acme/way-old", NOW - timedelta(days=30), pipeline_tag="text-generation", downloads=9e9
        ),
    ]

    def handler(request: httpx.Request) -> httpx.Response:
        if "cursor" not in str(request.url):
            return httpx.Response(
                200, json=page1, headers={"Link": '<https://hf/api/models?cursor=X>; rel="next"'}
            )
        return httpx.Response(200, json=page2)  # no Link → last page

    drafts = HuggingFaceCollector(client=_client(handler), min_interval_s=0).discover(WINDOW)
    captured = {d.source_event_uid for d in drafts}
    assert captured == {
        "model_discovered:acme/llm-chat",
        "model_discovered:acme/agent-tool",
    }
    assert all(d.source == "hf" and d.event_type == "model_discovered" for d in drafts)


def test_hf_fetch_by_author_keeps_created_at() -> None:
    """The hindcast seed path: list an org's models, preserving each model's real birth date."""
    born = datetime(2024, 5, 1, tzinfo=UTC)

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.params.get("author") == "deepseek-ai"
        return httpx.Response(200, json=[_hf_model("deepseek-ai/DeepSeek-V2", born, downloads=10)])

    drafts = HuggingFaceCollector(client=_client(handler), min_interval_s=0).fetch_by_author(
        ["deepseek-ai"]
    )
    assert len(drafts) == 1
    assert drafts[0].source_event_uid == "model_discovered:deepseek-ai/deepseek-v2"
    assert drafts[0].occurred_at == born


def test_hf_track_snapshots_downloads_and_skips_gone() -> None:
    """A gated/deleted model (401/404) skips that target; a live one yields a downloads snapshot."""

    def handler(request: httpx.Request) -> httpx.Response:
        if "gone/model" in str(request.url):
            return httpx.Response(404, json={"error": "Repo not found"})
        return httpx.Response(200, json={"id": "live/model", "downloads": 4200, "likes": 30})

    targets = [
        TrackTarget(entity_id=1, source="hf", native_id="gone/model"),
        TrackTarget(entity_id=2, source="hf", native_id="live/model"),
    ]
    drafts = HuggingFaceCollector(client=_client(handler), min_interval_s=0).track(targets, WINDOW)
    assert len(drafts) == 1
    assert drafts[0].event_type == "model_snapshot"
    assert drafts[0].payload["downloads"] == 4200


def test_hf_track_skips_transient_network_errors() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if "flaky/model" in str(request.url):
            raise httpx.RemoteProtocolError("server disconnected")
        return httpx.Response(200, json={"id": "live/model", "downloads": 7, "likes": 1})

    targets = [
        TrackTarget(entity_id=1, source="hf", native_id="flaky/model"),
        TrackTarget(entity_id=2, source="hf", native_id="live/model"),
    ]
    drafts = HuggingFaceCollector(client=_client(handler), min_interval_s=0).track(targets, WINDOW)
    assert len(drafts) == 1 and drafts[0].payload["downloads"] == 7


# --- PyPI (track snapshot + metadata enrichment) ----------------------------


def test_pypi_discover_is_empty() -> None:
    """PyPI has no trending feed — discover contributes nothing (anchors arrive via seeds/refs)."""

    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("discover() must not hit the network")

    assert PyPICollector(client=_client(handler), min_interval_s=0).discover(WINDOW) == []


def test_pypi_track_snapshots_downloads_and_skips_missing() -> None:
    """A live package yields a pypi_snapshot with downloads_7d; a 404 (no stats) skips it."""

    def handler(request: httpx.Request) -> httpx.Response:
        if "no-stats" in str(request.url):
            return httpx.Response(404, json={"message": "Not Found"})
        return httpx.Response(
            200,
            json={"data": {"last_day": 100, "last_week": 4200, "last_month": 18000},
                  "package": "vllm", "type": "recent_downloads"},
        )

    targets = [
        TrackTarget(entity_id=1, source="pypi", native_id="no-stats"),
        TrackTarget(entity_id=2, source="pypi", native_id="vllm"),
    ]
    drafts = PyPICollector(client=_client(handler), min_interval_s=0).track(targets, WINDOW)
    assert len(drafts) == 1, "the statless package is skipped, the live one still snapshots"
    d = drafts[0]
    assert d.source == "pypi" and d.event_type == "pypi_snapshot"
    assert d.payload == {"name": "vllm", "downloads_7d": 4200}


def test_pypi_track_skips_transient_network_errors() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if "flaky" in str(request.url):
            raise httpx.RemoteProtocolError("server disconnected")
        return httpx.Response(200, json={"data": {"last_week": 7}})

    targets = [
        TrackTarget(entity_id=1, source="pypi", native_id="flaky"),
        TrackTarget(entity_id=2, source="pypi", native_id="live"),
    ]
    drafts = PyPICollector(client=_client(handler), min_interval_s=0).track(targets, WINDOW)
    assert len(drafts) == 1 and drafts[0].payload["downloads_7d"] == 7


def test_pypi_metadata_records_requires_dist_and_skips_missing() -> None:
    """A live package yields a pypi_metadata event with requires_dist; a 404 skips that target."""

    def handler(request: httpx.Request) -> httpx.Response:
        if "gone" in str(request.url):
            return httpx.Response(404, json={"message": "Not Found"})
        return httpx.Response(
            200,
            json={"info": {
                "summary": "A high-throughput LLM inference engine.",
                "requires_dist": ["torch>=2.0", "transformers>=4.40"],
                "project_urls": {"Homepage": "https://github.com/vllm-project/vllm"},
            }},
        )

    targets = [
        TrackTarget(entity_id=1, source="pypi", native_id="gone"),
        TrackTarget(entity_id=2, source="pypi", native_id="vllm"),
    ]
    drafts = PyPICollector(client=_client(handler), min_interval_s=0).metadata(targets)
    assert len(drafts) == 1, "the gone package is skipped, the other still enriches"
    d = drafts[0]
    assert d.event_type == "pypi_metadata"
    assert d.source_event_uid == "pypi_metadata:vllm"  # idempotent per package
    assert d.payload["name"] == "vllm"
    assert d.payload["requires_dist"] == ["torch>=2.0", "transformers>=4.40"]
    assert d.payload["project_urls"]["Homepage"] == "https://github.com/vllm-project/vllm"
    assert d.payload["summary"] == "A high-throughput LLM inference engine."


def test_pypi_metadata_defaults_missing_fields() -> None:
    """A sparse package (no requires_dist/project_urls) yields empty containers, not None."""

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, json={"info": {"summary": None}})

    targets = [TrackTarget(entity_id=1, source="pypi", native_id="bare")]
    drafts = PyPICollector(client=_client(handler), min_interval_s=0).metadata(targets)
    assert drafts[0].payload["requires_dist"] == []
    assert drafts[0].payload["project_urls"] == {}
    assert drafts[0].payload["summary"] is None


# --- OpenRouter (model listings + rankings usage) ---------------------------


def _or_models_payload() -> dict:
    return {
        "data": [
            {
                "id": "poolside/laguna-s-2.1",
                "canonical_slug": "poolside/laguna-s-2.1-20260720",
                "hugging_face_id": "poolside/Laguna-S-2.1",
                "name": "Poolside: Laguna S 2.1",
                "created": int((NOW - timedelta(days=1)).timestamp()),
                "pricing": {"prompt": "0.0000001", "completion": "0.0000002"},
                "context_length": 1048576,
            },
            {
                "id": "moonshotai/kimi-k3",
                "canonical_slug": "moonshotai/kimi-k3-20260715",
                "hugging_face_id": None,
                "name": "MoonshotAI: Kimi K3",
                "created": int((NOW - timedelta(days=30)).timestamp()),  # old — not re-listed
                "pricing": {},
            },
        ]
    }


def _or_handler(rankings_status: int = 200) -> object:
    def handler(request: httpx.Request) -> httpx.Response:
        url = str(request.url)
        if "/api/v1/models" in url:
            return httpx.Response(200, json=_or_models_payload())
        if "/rankings/tools" in url:
            return httpx.Response(
                rankings_status,
                json={
                    "data": [
                        # In-window weekly point: a listed model and a delisted slug.
                        {
                            "x": "2026-06-30",
                            "ys": {
                                "moonshotai/kimi-k3-20260715": 123,
                                "moonshotai/kimi-k3-20260715:free": 7,
                                "gone/x": 5,
                                "Others": 164790526,
                            },
                        },
                        {"x": "2026-05-01", "ys": {"moonshotai/kimi-k3-20260715": 99}},  # too old
                    ]
                },
            )
        return httpx.Response(404, json={"error": {"message": "Not Found", "code": 404}})

    return handler


def test_openrouter_lists_new_models_and_rankings_in_window() -> None:
    drafts = OpenRouterCollector(client=_client(_or_handler()), min_interval_s=0).discover(WINDOW)
    by_type = {d.event_type: d for d in drafts}

    listed = by_type["or_model_listed"]  # only the model created inside the window
    assert listed.source_event_uid == "or_model:poolside/laguna-s-2.1"
    assert listed.payload["hugging_face_id"] == "poolside/Laguna-S-2.1"
    assert sum(d.event_type == "or_model_listed" for d in drafts) == 1

    ranks = [d for d in drafts if d.event_type == "or_rankings"]
    uids = sorted(d.source_event_uid for d in ranks)
    assert uids == [  # in-window point only; the "Others" aggregate bucket is not a model
        "or_rank:tools:2026-06-30:gone/x",
        "or_rank:tools:2026-06-30:moonshotai/kimi-k3-20260715",
        "or_rank:tools:2026-06-30:moonshotai/kimi-k3-20260715:free",
    ]
    kimi = next(d for d in ranks if d.source_event_uid.endswith("kimi-k3-20260715"))
    assert kimi.payload["tokens"] == 123
    # Metadata joined from the model list via canonical_slug, so identity can anchor the event.
    assert kimi.payload["name"] == "MoonshotAI: Kimi K3"
    free = next(d for d in ranks if d.source_event_uid.endswith(":free"))
    assert free.payload["name"] == "MoonshotAI: Kimi K3", "variant shares base-model identity"
    gone = next(d for d in ranks if "gone/x" in d.source_event_uid)
    assert gone.payload["name"] is None, "a delisted slug carries no metadata (stays unowned)"


def test_openrouter_rerun_yields_identical_uids() -> None:
    """Same window, same payloads -> byte-identical natural keys (framework dedupe no-ops)."""
    collector = OpenRouterCollector(client=_client(_or_handler()), min_interval_s=0)
    first = sorted(d.source_event_uid for d in collector.discover(WINDOW))
    second = sorted(d.source_event_uid for d in collector.discover(WINDOW))
    assert first == second


def test_openrouter_dead_rankings_category_is_isolated() -> None:
    """The rankings endpoints are unofficial: a dead category skips, the model list still lands."""
    drafts = OpenRouterCollector(
        client=_client(_or_handler(rankings_status=404)), min_interval_s=0
    ).discover(WINDOW)
    assert [d.event_type for d in drafts] == ["or_model_listed"]


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
