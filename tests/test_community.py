from __future__ import annotations

import itertools
import json
from datetime import UTC, datetime, timedelta
from decimal import Decimal

from sqlalchemy import text
from sqlalchemy.orm import Session

from seismo.community.queries import generate_queries
from seismo.community.relevance import CommunityThread, score_thread
from seismo.community.targets import CommunityTarget, select_community_targets

_UID = itertools.count(1)


def _json(v: dict) -> str:
    return json.dumps(v)


def _entity(
    session: Session,
    name: str,
    *,
    created: datetime,
    attrs: dict | None = None,
    tracking_tier: str = "active",
) -> int:
    return int(
        session.execute(
            text(
                "INSERT INTO entities"
                " (entity_type, canonical_name, created_at, attrs, tracking_tier)"
                " VALUES ('project', :n, :c, CAST(:a AS JSONB), :tier) RETURNING id"
            ),
            {"n": name, "c": created, "a": _json(attrs or {}), "tier": tracking_tier},
        ).scalar_one()
    )


def _target(**kwargs: object) -> CommunityTarget:
    return CommunityTarget(
        entity_id=1,
        canonical_name=str(kwargs.get("canonical_name", "acme/tool")),
        entity_type="project",
        category="inference-runtime",
        anchors=dict(kwargs.get("anchors", {"github": "acme/tool"})),
        owner=kwargs.get("owner", "acme"),  # type: ignore[arg-type]
        description=None,
        card={"what_it_is": "Fast inference runtime"},
        state="breakout",
        last_researched_at=None,
        last_status=None,
    )


def test_generate_queries_prefers_precise_anchors() -> None:
    queries = generate_queries(_target(), limit=5)
    assert queries[:3] == ['"acme/tool"', '"tool" "acme"', '"tool" github']
    assert '"acme/tool"' in queries


def test_relevance_accepts_exact_repo_and_rejects_ambiguous_name() -> None:
    target = _target(canonical_name="Crew", anchors={"github": "acme/crew"}, owner="acme")
    good = CommunityThread(
        thread_id="1",
        title="Anyone tried acme/crew for agents?",
        source="hn",
        channel="Hacker News",
        url="https://news.ycombinator.com/item?id=1",
        score=80,
        comment_count=12,
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    bad = CommunityThread(
        thread_id="2",
        title="Best crew scheduling tools?",
        source="hn",
        channel="Hacker News",
        url="https://news.ycombinator.com/item?id=2",
        score=100,
        comment_count=30,
        created_at=datetime(2026, 1, 1, tzinfo=UTC),
    )
    assert score_thread(target, good).relevance_score >= 60
    assert score_thread(target, bad).relevance_score < 60


def test_target_selector_respects_due_cadence(clean_db: Session) -> None:
    session = clean_db
    now = datetime(2026, 7, 24, tzinfo=UTC)
    fresh = _entity(session, "fresh", created=now, attrs={"anchors": {"github": "acme/fresh"}})
    stale = _entity(session, "stale", created=now, attrs={"anchors": {"github": "acme/stale"}})
    archived = _entity(
        session,
        "archived",
        created=now,
        attrs={"anchors": {"github": "acme/archived"}},
        tracking_tier="archived",
    )
    for eid, state in [(fresh, "breakout"), (stale, "dormant"), (archived, "breakout")]:
        session.execute(
            text(
                "INSERT INTO momentum_states (entity_id, day, state, inputs)"
                " VALUES (:e, :d, :s, CAST('{}' AS JSONB))"
            ),
            {"e": eid, "d": now.date(), "s": state},
        )
    session.execute(
        text(
            """
            INSERT INTO entity_community_research
              (entity_id, source, status, query_set, result, researched_at)
            VALUES
              (:e, 'github', 'found', CAST(:q AS JSONB), CAST(:r AS JSONB), :ts)
            """
        ),
        {
            "e": fresh,
            "q": _json({"queries": ['"fresh"']}),
            "r": _json({"status": "found", "summary": "ok", "threads": []}),
            "ts": now - timedelta(hours=12),
        },
    )
    session.flush()

    targets = select_community_targets(session, "github", as_of=now, limit=10)
    names = {t.canonical_name for t in targets}
    assert "fresh" not in names
    assert "stale" in names
    assert "archived" not in names


class _FakeClient:
    """A CommunityClient stand-in that only serves entities with a github anchor."""

    source = "github"

    def __init__(self, threads: list[CommunityThread]) -> None:
        self._threads = threads
        self.closed = False
        self.served: list[str] = []

    def applies_to(self, target: CommunityTarget) -> bool:
        return bool(target.anchors.get("github"))

    def fetch_threads(
        self, target: CommunityTarget, queries: list[str], *, limit: int
    ) -> list[CommunityThread]:
        self.served.append(target.canonical_name)
        return [
            CommunityThread(
                thread_id=t.thread_id,
                title=t.title,
                source=t.source,
                channel=t.channel,
                url=t.url,
                score=t.score,
                comment_count=t.comment_count,
            )
            for t in self._threads
        ]

    def comments(self, thread: CommunityThread, *, limit: int) -> list[str]:
        return ["Works great in production.", "Docs are thin though."][:limit]

    def close(self) -> None:
        self.closed = True


def test_runner_gates_by_applies_to_and_persists_per_source(clean_db: Session) -> None:
    from seismo.community.runner import run_community_research

    session = clean_db
    now = datetime(2026, 7, 24, tzinfo=UTC)
    repo = _entity(session, "repo-proj", created=now, attrs={"anchors": {"github": "acme/repo"}})
    paper = _entity(session, "paper-only", created=now, attrs={"anchors": {"arxiv": "2401.00001"}})
    session.flush()

    thread = CommunityThread(
        thread_id="issue:acme/repo#1",
        title="acme/repo crashes on start",
        source="github",
        channel="GitHub Issues",
        url="https://github.com/acme/repo/issues/1",  # url carries the anchor → scores >= 60
        score=40,
        comment_count=12,
    )
    client = _FakeClient([thread])

    stats = run_community_research(
        session, source="github", as_of=now, force=True, client=client
    )

    # Only the github-anchored entity is served; the arxiv-only paper is skipped entirely.
    assert client.served == ["repo-proj"]
    assert stats.selected == 1
    assert stats.found == 1

    rows = session.execute(
        text(
            "SELECT entity_id, source, status, result FROM entity_community_research"
            " ORDER BY entity_id"
        )
    ).mappings().all()
    assert len(rows) == 1
    row = rows[0]
    assert row["entity_id"] == repo
    assert row["source"] == "github"
    assert row["status"] == "found"
    persisted = row["result"]["threads"][0]
    assert persisted["channel"] == "GitHub Issues"
    assert persisted["source"] == "github"
    assert paper not in {r["entity_id"] for r in rows}



def test_community_synthesis_writes_verdict_row(clean_db: Session, monkeypatch) -> None:
    from seismo.checkpoints.llm import LLMResult
    from seismo.community import verdict as vmod
    from seismo.community.verdict import run_community_synthesis

    # Provider-independent: stub the LLM to a fixed verdict so the test never needs a real provider.
    def _fake_complete(system, user, schema, *, fallback, purpose="live"):  # noqa: ANN001
        return LLMResult(
            content={
                "overall_sentiment": "mostly_positive",
                "sentiment_score": 72,
                "summary": "Users report it works after an early crash was fixed.",
                "positive_signals": ["Fix landed quickly"],
                "concerns": ["Crashed on start initially"],
                "main_points": ["Startup stability"],
                "notable_quotes": ["Works now, thanks!"],
            },
            model="mock",
            cost_usd=Decimal(0),
        )

    monkeypatch.setattr(vmod, "complete_community", _fake_complete)

    session = clean_db
    now = datetime(2026, 7, 24, tzinfo=UTC)
    eid = _entity(session, "verdict-proj", created=now, attrs={"anchors": {"github": "acme/vp"}})
    # A collected per-source row with real threads + comments — the synthesis input.
    src_result = {
        "status": "found",
        "summary": "found",
        "threads": [
            {
                "id": "issue:acme/vp#1",
                "title": "Crashes on start",
                "channel": "GitHub Issues",
                "comment_count": 3,
                "comments": ["Same here on macOS.", "A fix landed in v2.", "Works now, thanks!"],
            }
        ],
    }
    session.execute(
        text(
            """
            INSERT INTO entity_community_research
              (entity_id, source, status, query_set, result, researched_at)
            VALUES (:e, 'github', 'found', CAST(:q AS JSONB), CAST(:r AS JSONB), :ts)
            """
        ),
        {"e": eid, "q": _json({"queries": []}), "r": _json(src_result), "ts": now},
    )
    session.flush()

    stats = run_community_synthesis(session, as_of=now, force=True)
    assert stats.summarized == 1

    row = session.execute(
        text(
            "SELECT status, result, model FROM entity_community_research"
            " WHERE entity_id=:e AND source='summary' ORDER BY id DESC LIMIT 1"
        ),
        {"e": eid},
    ).mappings().one()
    assert row["status"] == "found"
    assert row["model"] == "mock"
    v = row["result"]
    assert v["kpis"]["thread_count"] == 1
    assert v["kpis"]["comment_count"] == 3  # comments were read from the per-source row
    assert v["sentiment"] == "mostly_positive"
    assert v["sentiment_score"] == 72
    assert v["concerns"] == ["Crashed on start initially"]
    assert v["notable_quotes"] == ["Works now, thanks!"]
    assert v["threads"] == []  # the verdict is a synthesis; threads live on the per-source rows


def test_community_synthesis_skips_entities_without_comments(clean_db: Session) -> None:
    from seismo.community.verdict import run_community_synthesis

    session = clean_db
    now = datetime(2026, 7, 24, tzinfo=UTC)
    eid = _entity(session, "empty-proj", created=now, attrs={"anchors": {"github": "acme/ep"}})
    # A 'found' row that carries no threads → nothing quotable to summarize.
    session.execute(
        text(
            """
            INSERT INTO entity_community_research
              (entity_id, source, status, query_set, result, researched_at)
            VALUES (:e, 'github', 'found', CAST('{}' AS JSONB), CAST(:r AS JSONB), :ts)
            """
        ),
        {"e": eid, "r": _json({"status": "found", "threads": []}), "ts": now},
    )
    session.flush()

    stats = run_community_synthesis(session, as_of=now, force=True)
    assert stats.skipped == 1
    row = session.execute(
        text(
            "SELECT status FROM entity_community_research"
            " WHERE entity_id=:e AND source='summary'"
        ),
        {"e": eid},
    ).scalar_one()
    assert row == "not_found"


# --- verdict run control: termination, budget, concurrency (resume §5–6) --------------------

_STUB_VERDICT = {
    "overall_sentiment": "mixed",
    "sentiment_score": 50,
    "summary": "Discussion is split.",
    "positive_signals": ["Fast"],
    "concerns": ["Docs are thin"],
    "main_points": ["Performance"],
    "notable_quotes": ["It's fast."],
}


def _stub_llm(monkeypatch, *, cost: str = "0") -> list[str]:
    """Replace the LLM with a fixed verdict. Returns the list that records each call's prompt, so a
    test can assert how many entities were actually billed."""
    from seismo.checkpoints.llm import LLMResult
    from seismo.community import verdict as vmod

    seen: list[str] = []

    def _fake(system, user, schema, *, fallback, purpose="live"):  # noqa: ANN001
        seen.append(user)
        return LLMResult(
            content=dict(_STUB_VERDICT),
            model="mock",
            cost_usd=Decimal(cost),
            input_tokens=100,
            output_tokens=20,
        )

    monkeypatch.setattr(vmod, "complete_community", _fake)
    return seen


def _entity_with_discussion(session: Session, name: str, *, when: datetime) -> int:
    """An entity carrying one collected GitHub thread with comments — a synthesis input."""
    eid = _entity(session, name, created=when, attrs={"anchors": {"github": f"acme/{name}"}})
    session.execute(
        text(
            """
            INSERT INTO entity_community_research
              (entity_id, source, status, query_set, result, researched_at)
            VALUES (:e, 'github', 'found', CAST('{}' AS JSONB), CAST(:r AS JSONB), :ts)
            """
        ),
        {
            "e": eid,
            "r": _json(
                {
                    "status": "found",
                    "threads": [
                        {
                            "id": f"issue:acme/{name}#1",
                            "title": "Crashes on start",
                            "channel": "GitHub Issues",
                            "comment_count": 2,
                            "comments": ["Same here.", "Fixed in v2."],
                        }
                    ],
                }
            ),
            "ts": when,
        },
    )
    session.flush()
    return eid


def test_force_with_limit_is_rejected(clean_db: Session) -> None:
    """Landmine #1: force + limit re-selects the same top N forever, billing every pass."""
    import pytest

    from seismo.community.verdict import run_community_synthesis

    now = datetime(2026, 7, 24, tzinfo=UTC)
    with pytest.raises(ValueError, match="never terminates"):
        run_community_synthesis(clean_db, as_of=now, limit=10, force=True)
    # Still allowed for a single entity, where re-selection cannot loop.
    run_community_synthesis(clean_db, as_of=now, limit=10, entity_id=-1, force=True)


def test_redo_before_drains_the_backlog_in_batches(clean_db: Session, monkeypatch) -> None:
    """The terminating replacement for force+limit: each pass shrinks the selection to zero, and
    the superseded verdicts stay on the table (append-only history, resume §8)."""
    from seismo.community.verdict import run_community_synthesis

    calls = _stub_llm(monkeypatch)
    session = clean_db
    now = datetime(2026, 7, 24, tzinfo=UTC)
    for n in ("alpha", "beta", "gamma"):
        _entity_with_discussion(session, n, when=now)

    # Pre-existing (stale-model) verdicts for all three, as the qwen backlog looks today.
    run_community_synthesis(session, as_of=now)
    assert len(calls) == 3

    cutoff = datetime.now(UTC)
    seen = []
    for _ in range(5):  # the drain loop from the runbook, bounded so a bug fails fast
        stats = run_community_synthesis(session, as_of=now, limit=2, redo_before=cutoff)
        seen.append(stats.selected)
        if stats.selected == 0:
            break
    assert seen == [2, 1, 0], seen
    assert len(calls) == 6  # each entity re-summarized exactly once, none re-billed

    # Append-only: the superseded rows were never deleted.
    total = session.execute(
        text("SELECT count(*) FROM entity_community_research WHERE source='summary'")
    ).scalar_one()
    assert total == 6


def test_budget_stops_the_run(clean_db: Session, monkeypatch) -> None:
    """Landmine #3: llm_budget_usd was never consulted on this path."""
    from seismo.community.verdict import run_community_synthesis

    calls = _stub_llm(monkeypatch, cost="1.00")
    session = clean_db
    now = datetime(2026, 7, 24, tzinfo=UTC)
    for i in range(9):
        _entity_with_discussion(session, f"budget-{i}", when=now)

    stats = run_community_synthesis(session, as_of=now, budget_usd=2.0)
    assert stats.selected == 9
    # Checked per chunk, so spend overshoots by at most one chunk rather than running to the end.
    assert stats.summarized == 4
    assert len(calls) == 4
    assert stats.cost_usd == Decimal("4.00")
    assert stats.stopped_reason and "budget" in stats.stopped_reason


def test_concurrency_summarizes_every_entity_once(clean_db: Session, monkeypatch) -> None:
    from seismo.community.verdict import run_community_synthesis

    calls = _stub_llm(monkeypatch)
    session = clean_db
    now = datetime(2026, 7, 24, tzinfo=UTC)
    for i in range(10):
        _entity_with_discussion(session, f"par-{i}", when=now)

    stats = run_community_synthesis(session, as_of=now, concurrency=5)
    assert (stats.summarized, stats.failed, stats.skipped) == (10, 0, 0)
    assert len(calls) == 10
    rows = session.execute(
        text(
            "SELECT count(DISTINCT entity_id) FROM entity_community_research"
            " WHERE source='summary'"
        )
    ).scalar_one()
    assert rows == 10


def test_one_bad_generation_does_not_abort_the_batch(clean_db: Session, monkeypatch) -> None:
    from seismo.checkpoints.llm import LLMResult
    from seismo.community import verdict as vmod
    from seismo.community.verdict import run_community_synthesis

    session = clean_db
    now = datetime(2026, 7, 24, tzinfo=UTC)
    for i in range(4):
        _entity_with_discussion(session, f"flaky-{i}", when=now)

    def _fake(system, user, schema, *, fallback, purpose="live"):  # noqa: ANN001
        if "flaky-2" in user:
            raise RuntimeError("overloaded_error")
        return LLMResult(content=dict(_STUB_VERDICT), model="mock", cost_usd=Decimal(0))

    monkeypatch.setattr(vmod, "complete_community", _fake)
    stats = run_community_synthesis(session, as_of=now, concurrency=3)
    assert (stats.summarized, stats.failed) == (3, 1)
    statuses = dict(
        session.execute(
            text(
                "SELECT e.canonical_name, r.status FROM entity_community_research r"
                " JOIN entities e ON e.id=r.entity_id WHERE r.source='summary'"
            )
        ).all()
    )
    assert statuses["flaky-2"] == "failed"


def test_bare_word_web_anchor_earns_no_anchor_credit() -> None:
    """Landmine #2 root cause: the entity 'Echo' stores web='echo', which matched any thread
    containing the word — four Amazon-smart-speaker HN stories cleared the threshold that way."""
    thread = CommunityThread(
        thread_id="1",
        title="Amazon Echo",
        source="hn",
        channel="Hacker News",
        url="https://news.ycombinator.com/item?id=1",
        body="https://amazon.com/echo",
        score=80,
        comment_count=40,
    )
    bare = score_thread(_target(canonical_name="Echo", anchors={"web": "echo"}, owner=None), thread)
    assert bare.relevance_score < 60  # dropped instead of poisoning the verdict

    real = score_thread(
        _target(canonical_name="Echo", anchors={"web": "https://echo.dev/docs"}, owner=None),
        CommunityThread(
            thread_id="2",
            title="Show HN: Echo",
            source="hn",
            channel="Hacker News",
            url="https://news.ycombinator.com/item?id=2",
            body="https://echo.dev",  # a real homepage match still earns its 30 points
            score=80,
            comment_count=40,
        ),
    )
    assert real.relevance_score >= 60


# --- claude_cli provider + the zero-comment gate -------------------------------------------

def _cli_envelope(result: str, *, cost: float = 0.05, is_error: bool = False) -> str:
    return json.dumps(
        {
            "is_error": is_error,
            "result": result,
            "total_cost_usd": cost,
            "usage": {"input_tokens": 500, "output_tokens": 400},
        }
    )


def test_claude_cli_pins_the_model_and_constrains_output(monkeypatch) -> None:
    """The CLI has no forced tool call; --json-schema is what constrains the reply. Also asserts
    --bare is NOT passed: it suppresses keychain reads, so every call comes back 'Not logged in'
    and — because this path fails closed — does so silently."""
    import subprocess

    from seismo.checkpoints.llm import _claude_cli_metered

    seen: dict = {}

    def _fake_run(cmd, **kw):  # noqa: ANN001
        seen["cmd"] = cmd
        return subprocess.CompletedProcess(
            cmd, 0, stdout=_cli_envelope('{"overall_sentiment": "mixed"}'), stderr=""
        )

    monkeypatch.setattr(subprocess, "run", _fake_run)
    out = _claude_cli_metered("prompt", {"type": "object"}, model="claude-haiku-4-5")

    assert out.parsed == {"overall_sentiment": "mixed"}
    assert out.cost_usd == Decimal("0.05")  # feeds llm_budget_usd
    cmd = seen["cmd"]
    assert cmd[cmd.index("--model") + 1] == "claude-haiku-4-5"  # pinned, not claude_cli_model
    assert "--json-schema" in cmd
    assert "--bare" not in cmd


def test_claude_cli_fails_closed_but_community_fails_loud(monkeypatch) -> None:
    """Cards/briefs prefer a degraded result over a broken run; a bulk backlog must not silently
    store a fallback that reads exactly like a real verdict."""
    import subprocess

    import pytest

    from seismo.checkpoints import llm as llm_mod

    def _fake_run(cmd, **kw):  # noqa: ANN001
        return subprocess.CompletedProcess(
            cmd, 0, stdout=_cli_envelope("Could you provide the comments?"), stderr=""
        )

    monkeypatch.setattr(subprocess, "run", _fake_run)

    # fail-closed: parsed is None, never raises
    assert llm_mod._claude_cli("prompt", {"type": "object"}) is None  # main's contract

    # fail-loud once strict_cli is set (what complete_community passes)
    monkeypatch.setattr(llm_mod.settings, "community_llm_provider", "claude_cli", raising=False)
    monkeypatch.setattr(llm_mod.settings, "community_model", "claude-haiku-4-5", raising=False)
    with pytest.raises(RuntimeError, match="no structured result"):
        llm_mod.complete_community("sys", "user", {"type": "object"}, fallback={"x": 1})


def test_threads_without_comments_are_never_billed(clean_db: Session, monkeypatch) -> None:
    """32% of collected entities carry thread titles with no comment bodies. There is nothing to
    summarize from a title, so these must not reach the model at all."""
    from seismo.community.verdict import run_community_synthesis

    calls = _stub_llm(monkeypatch, cost="0.05")
    session = clean_db
    now = datetime(2026, 7, 24, tzinfo=UTC)
    eid = _entity(session, "titles-only", created=now, attrs={"anchors": {"github": "acme/t"}})
    session.execute(
        text(
            """
            INSERT INTO entity_community_research
              (entity_id, source, status, query_set, result, researched_at)
            VALUES (:e, 'github', 'found', CAST('{}' AS JSONB), CAST(:r AS JSONB), :ts)
            """
        ),
        {
            "e": eid,
            "r": _json(
                {
                    "status": "found",
                    "threads": [
                        {"id": "1", "title": "Store metadata in SQLite", "comments": []},
                        {"id": "2", "title": "Add retry logic", "comments": []},
                    ],
                }
            ),
            "ts": now,
        },
    )
    session.flush()

    stats = run_community_synthesis(session, as_of=now)
    assert (stats.summarized, stats.skipped) == (0, 1)
    assert calls == []  # never reached the model
    assert stats.cost_usd == Decimal(0)

    row = session.execute(
        text(
            "SELECT status, result FROM entity_community_research"
            " WHERE entity_id=:e AND source='summary' ORDER BY id DESC LIMIT 1"
        ),
        {"e": eid},
    ).mappings().one()
    assert row["status"] == "not_found"
    # The threads we did collect are still reported rather than implying nothing was found.
    assert row["result"]["kpis"]["thread_count"] == 2
    assert "none carry comment text" in row["result"]["summary"]


def test_json_object_is_extracted_from_surrounding_prose() -> None:
    """The CLI has no forced tool call, so replies arrive fenced, prefaced, or annotated."""
    from seismo.checkpoints.llm import _first_json_object

    obj = {"overall_sentiment": "mixed", "summary": 'He said "it depends" — and {braces} too'}
    body = json.dumps(obj)
    for reply in (
        body,
        f"```json\n{body}\n```",
        f"Here is the verdict:\n{body}",
        f"{body}\n\nLet me know if you'd like more detail.",
        f"Sure — here you go.\n```\n{body}\n```\nHope that helps!",
    ):
        assert _first_json_object(reply) == obj, reply[:40]

    assert _first_json_object("I need the actual comments to analyze.") is None
    assert _first_json_object('{"truncated": ') is None  # never returns a half-parsed object


def test_failed_verdicts_stay_selectable_for_retry(clean_db: Session, monkeypatch) -> None:
    """A failed verdict is stamped now() — newer than the source rows — so without an explicit
    status check it would lock the entity out of every later run. Re-running is the retry."""
    from seismo.checkpoints.llm import LLMResult
    from seismo.community import verdict as vmod
    from seismo.community.verdict import run_community_synthesis

    session = clean_db
    now = datetime(2026, 7, 24, tzinfo=UTC)
    _entity_with_discussion(session, "flaky-once", when=now)

    attempts: list[int] = []

    def _fake(system, user, schema, *, fallback, purpose="live"):  # noqa: ANN001
        attempts.append(1)
        if len(attempts) == 1:
            raise RuntimeError("rate limited")
        return LLMResult(content=dict(_STUB_VERDICT), model="mock", cost_usd=Decimal(0))

    monkeypatch.setattr(vmod, "complete_community", _fake)

    first = run_community_synthesis(session, as_of=now)
    assert (first.summarized, first.failed) == (0, 1)

    second = run_community_synthesis(session, as_of=now)  # same command again = the retry
    assert (second.selected, second.summarized) == (1, 1)

    third = run_community_synthesis(session, as_of=now)  # now settled, not re-selected
    assert third.selected == 0


def test_newer_not_found_supersedes_an_older_found_row(clean_db: Session, monkeypatch) -> None:
    """Re-collecting a source and finding nothing must clear the previous result. Filtering to
    status='found' before picking the newest row per source resurrects stale data forever — which
    is how Echo kept summarizing four Amazon smart-speaker threads after its HN row had already
    been re-collected as not_found."""
    from seismo.community.verdict import _load_sources, run_community_synthesis

    calls = _stub_llm(monkeypatch)
    session = clean_db
    now = datetime(2026, 7, 24, tzinfo=UTC)
    eid = _entity(session, "collided", created=now, attrs={"anchors": {"github": "acme/c"}})

    def _row(status: str, threads: list, ts: datetime) -> None:
        session.execute(
            text(
                """
                INSERT INTO entity_community_research
                  (entity_id, source, status, query_set, result, researched_at)
                VALUES (:e, 'hn', :st, CAST('{}' AS JSONB), CAST(:r AS JSONB), :ts)
                """
            ),
            {"e": eid, "st": status, "r": _json({"status": status, "threads": threads}), "ts": ts},
        )

    _row("found", [{"id": "1", "title": "Amazon Echo", "comments": ["Alexa is creepy."]}], now)
    session.flush()
    assert _load_sources(session, eid)  # the contaminated row is live

    # The relevance fix lands and the source is re-collected: nothing clears the bar any more.
    _row("not_found", [], now + timedelta(hours=1))
    session.flush()
    assert _load_sources(session, eid) == []

    stats = run_community_synthesis(session, as_of=now + timedelta(hours=2), force=True)
    assert (stats.summarized, stats.skipped) == (0, 1)
    assert calls == []  # nothing left to summarize, so nothing was billed
    assert session.execute(
        text(
            "SELECT status FROM entity_community_research"
            " WHERE entity_id=:e AND source='summary' ORDER BY id DESC LIMIT 1"
        ),
        {"e": eid},
    ).scalar_one() == "not_found"
