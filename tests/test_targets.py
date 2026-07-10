"""Track-target selection (doc 03 DR-03.3) — who gets deep-polled for repo_snapshot."""

from __future__ import annotations

from datetime import UTC, datetime

from sqlalchemy import text
from sqlalchemy.orm import Session

from seismo.collectors.targets import select_targets


def _entity(
    session: Session,
    name: str,
    *,
    anchors: dict | None = None,
    tier: str = "active",
    merged_into: int | None = None,
) -> int:
    import json

    attrs = {"anchors": anchors} if anchors else {}
    return int(
        session.execute(
            text(
                """
                INSERT INTO entities
                    (entity_type, canonical_name, created_at, attrs, tracking_tier, merged_into)
                VALUES ('project', :n, :c, CAST(:a AS JSONB), :t, :m) RETURNING id
                """
            ),
            {
                "n": name,
                "c": datetime(2024, 1, 1, tzinfo=UTC),
                "a": json.dumps(attrs),
                "t": tier,
                "m": merged_into,
            },
        ).scalar_one()
    )


def test_select_targets_returns_active_github_entities(clean_db: Session) -> None:
    session = clean_db
    tracked = _entity(session, "vllm", anchors={"github": "vllm-project/vllm"})
    _entity(session, "paper-only", anchors={"arxiv": "2401.00001"})  # no github anchor
    _entity(session, "archived", anchors={"github": "old/repo"}, tier="archived")
    survivor = _entity(session, "survivor", anchors={"github": "org/keep"})
    _entity(session, "merged", anchors={"github": "org/dupe"}, merged_into=survivor)
    session.flush()

    targets = select_targets(session, "github")
    ids = {t.entity_id for t in targets}
    assert tracked in ids and survivor in ids
    assert len(targets) == 2, "only active, unmerged, github-anchored entities are tracked"
    native = {t.native_id for t in targets}
    assert native == {"vllm-project/vllm", "org/keep"}
    assert all(t.source == "github" for t in targets)


def test_select_targets_respects_limit(clean_db: Session) -> None:
    session = clean_db
    for i in range(5):
        _entity(session, f"r{i}", anchors={"github": f"org/r{i}"})
    session.flush()
    assert len(select_targets(session, "github", limit=3)) == 3


def test_unknown_source_has_no_targets(clean_db: Session) -> None:
    assert select_targets(clean_db, "pypi") == []
