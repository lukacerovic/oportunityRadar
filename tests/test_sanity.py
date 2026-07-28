"""Content-sanity checkpoint (``checkpoints/sanity.py``) — judges freshly-collected README/model-
card/launch/discussion/abstract text for legibility, batched, never mutating ``raw_events``.

Runs on ``clean_db`` with the default ``mock`` provider ($0, no network). The one budget test flips
the provider to ``anthropic`` but sets the budget to 0 so the call is never attempted (mirrors
``test_comprehension.py``'s ``test_budget_ceiling_marks_pending_without_calling``).
"""

from __future__ import annotations

import itertools
from datetime import UTC, datetime

from sqlalchemy import text
from sqlalchemy.orm import Session

from seismo.checkpoints import sanity as san
from seismo.config import settings

_UID = itertools.count(1)


def _raw_event(session: Session, event_type: str, payload: dict, *, occurred: datetime) -> int:
    import json

    return int(
        session.execute(
            text(
                "INSERT INTO raw_events (source, source_event_uid, event_type, occurred_at,"
                " payload) VALUES ('github', :uid, :et, :o, CAST(:p AS JSONB)) RETURNING id"
            ),
            {"uid": f"uid-{next(_UID)}", "et": event_type, "o": occurred, "p": json.dumps(payload)},
        ).scalar_one()
    )


def test_run_sanity_mock_provider_end_to_end(clean_db: Session) -> None:
    session = clean_db
    t0 = datetime(2024, 1, 1, tzinfo=UTC)
    rid = _raw_event(
        session,
        "repo_readme",
        {"full_name": "acme/widget", "text": "A real README about a real widget."},
        occurred=t0,
    )
    session.flush()

    stats = san.run_sanity(session, t0)

    assert stats.candidates == 1
    assert stats.ok == 1 and stats.flagged == 0 and stats.rejected == 0
    assert stats.cost_usd == 0  # mock provider

    row = session.execute(
        text("SELECT verdict, model, cost_usd FROM content_sanity_checks WHERE raw_event_id = :r"),
        {"r": rid},
    ).one()
    assert row[0] == "ok"
    assert row[1] == "mock"
    assert row[2] == 0


def test_run_sanity_is_idempotent(clean_db: Session) -> None:
    session = clean_db
    t0 = datetime(2024, 1, 1, tzinfo=UTC)
    _raw_event(session, "launch_page", {"text": "A launch page with real content."}, occurred=t0)
    session.flush()

    first = san.run_sanity(session, t0)
    second = san.run_sanity(session, t0)

    assert first.candidates == 1
    assert second.candidates == 0  # already checked — nothing left to do
    n = session.execute(text("SELECT COUNT(*) FROM content_sanity_checks")).scalar_one()
    assert n == 1


def test_only_text_bearing_event_types_are_candidates(clean_db: Session) -> None:
    session = clean_db
    t0 = datetime(2024, 1, 1, tzinfo=UTC)
    # repo_snapshot carries star counts, no readable text — must never become a sanity candidate.
    _raw_event(session, "repo_snapshot", {"stars": 42}, occurred=t0)
    session.flush()

    stats = san.run_sanity(session, t0)

    assert stats.candidates == 0
    n = session.execute(text("SELECT COUNT(*) FROM content_sanity_checks")).scalar_one()
    assert n == 0


def test_budget_ceiling_skips_without_calling(clean_db: Session, monkeypatch) -> None:
    session = clean_db
    t0 = datetime(2024, 1, 1, tzinfo=UTC)
    _raw_event(session, "model_readme", {"text": "A model card with real content."}, occurred=t0)
    session.flush()

    monkeypatch.setattr(settings, "llm_provider", "anthropic")
    monkeypatch.setattr(settings, "sanity_llm_budget_usd", 0.0)
    # If the budget gate failed, this would try to hit the network and raise.
    stats = san.run_sanity(session, t0)

    assert stats.candidates == 1
    assert stats.skipped_budget == 1
    assert stats.ok == 0 and stats.flagged == 0 and stats.rejected == 0
    n = session.execute(text("SELECT COUNT(*) FROM content_sanity_checks")).scalar_one()
    assert n == 0  # nothing stored — retryable next run
