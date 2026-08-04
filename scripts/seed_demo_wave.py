"""Seed a DEMO wave so ``/waves`` can be reviewed before real data exists.

Reproduces the shape of ``AGENT_GUARDRAIL_WAVE.md``: six independent projects, none pointing at any
other, each with a semantic edge to its own neighbour, spanning two categories — plus one early
Hacker News mention and a usage series that makes the outcome measurable.

**Everything it writes is namespaced ``demo/`` and removable with ``--purge``.** This exists to look
at the screen, never to stand in for a finding. Do not run it against a database whose contents you
care about without reading what it inserts.

    uv run python scripts/seed_demo_wave.py          # insert, then run: uv run seismo waves
    uv run python scripts/seed_demo_wave.py --purge  # remove every demo/ row it created
"""

from __future__ import annotations

import sys
from datetime import UTC, datetime, timedelta

from sqlalchemy import text

from seismo.db import session_scope

PREFIX = "demo/"
FORMED = datetime(2026, 7, 2, tzinfo=UTC)
SAID_AT = datetime(2026, 6, 14, 12, 0, tzinfo=UTC)

MEMBERS = [
    ("coder_eval", "agent-framework", "demo-uipath"),
    ("termaxa", "agent-framework", "demo-termaxa"),
    ("r3-review", "agent-framework", "demo-hyperlogue"),
    ("open-record-replay", "agent-framework", "demo-videodb"),
    ("verbatimeter", "rag-framework", "demo-pob"),
    ("postern", "rag-framework", "demo-skyphusion"),
]


def purge() -> None:
    with session_scope() as s:
        ids = list(
            s.execute(
                text("SELECT id FROM entities WHERE canonical_name LIKE :p"), {"p": f"{PREFIX}%"}
            ).scalars()
        )
        if ids:
            s.execute(text("DELETE FROM wave_observations WHERE entity_id = ANY(:ids)"), {"ids": ids})
            s.execute(text("DELETE FROM wave_members WHERE entity_id = ANY(:ids)"), {"ids": ids})
            s.execute(
                text(
                    "DELETE FROM wave_outcomes WHERE wave_id IN"
                    " (SELECT id FROM wave_clusters WHERE id NOT IN"
                    "  (SELECT DISTINCT wave_id FROM wave_members))"
                )
            )
            s.execute(
                text(
                    "DELETE FROM wave_clusters WHERE id NOT IN"
                    " (SELECT DISTINCT wave_id FROM wave_members)"
                )
            )
            s.execute(text("DELETE FROM entity_semantic_edges WHERE src_entity_id = ANY(:ids)"), {"ids": ids})
            s.execute(text("DELETE FROM entity_metrics_daily WHERE entity_id = ANY(:ids)"), {"ids": ids})
            s.execute(text("DELETE FROM entity_category_history WHERE entity_id = ANY(:ids)"), {"ids": ids})
            s.execute(text("DELETE FROM entity_links WHERE entity_id = ANY(:ids)"), {"ids": ids})
            s.execute(text("DELETE FROM entities WHERE id = ANY(:ids)"), {"ids": ids})
        s.execute(text("DELETE FROM raw_events WHERE source_event_uid LIKE :p"), {"p": f"{PREFIX}%"})
    print(f"purged {len(ids)} demo entities")


def _entity(s, name: str, category: str | None, owner: str, first_seen: datetime) -> int:
    entity_id = s.execute(
        text(
            "INSERT INTO entities (entity_type, canonical_name, category, created_at, attrs)"
            " VALUES ('project', :name, :cat, :ts, CAST(:attrs AS jsonb)) RETURNING id"
        ),
        {
            "name": f"{PREFIX}{name}",
            "cat": category,
            "ts": first_seen,
            "attrs": f'{{"anchors": {{"github": "{owner}/{name}"}}}}',
        },
    ).scalar_one()
    event_id = s.execute(
        text(
            "INSERT INTO raw_events (source, source_event_uid, event_type, occurred_at, payload)"
            " VALUES ('github', :uid, 'repo_snapshot', :ts, CAST(:p AS jsonb)) RETURNING id"
        ),
        {"uid": f"{PREFIX}{name}", "ts": first_seen, "p": f'{{"name": "{name}"}}'},
    ).scalar_one()
    s.execute(
        text(
            "INSERT INTO entity_links (entity_id, raw_event_id, rule, confidence)"
            " VALUES (:e, :r, 'attach', 1.0)"
        ),
        {"e": entity_id, "r": event_id},
    )
    if category:
        # Cohorts read category through the history table (doc 13 A-2), not entities.category.
        s.execute(
            text(
                "INSERT INTO entity_category_history (entity_id, category, effective_at)"
                " VALUES (:e, :c, :ts)"
            ),
            {"e": entity_id, "c": category, "ts": first_seen},
        )
    return int(entity_id)


def seed() -> None:
    with session_scope() as s:
        member_ids = []
        for i, (name, category, owner) in enumerate(MEMBERS):
            # Members appear on staggered days so the window has a real span, as a wave does.
            member = _entity(s, name, category, owner, FORMED + timedelta(days=i * 3))
            member_ids.append(member)
            # Each member points at its OWN neighbour — never at another member. That is the shape
            # that makes naive connected-components find nothing.
            neighbour = _entity(
                s, f"neighbour-{i}", "guardrails", f"demo-nb{i}", FORMED - timedelta(days=400)
            )
            s.execute(
                text(
                    "INSERT INTO entity_semantic_edges (src_entity_id, dst_entity_id, src_label,"
                    " dst_label, relation, confidence, confidence_score, model)"
                    " VALUES (:src, :dst, :sl, :dl, 'semantically_similar_to', 'high', 0.9, 'demo')"
                ),
                {
                    "src": member,
                    "dst": neighbour,
                    "sl": name,
                    "dl": f"{PREFIX}neighbour-{i}",
                },
            )

        # One early mention, with a real author and real source time — the lead-time claim.
        s.execute(
            text(
                "INSERT INTO raw_events (source, source_event_uid, event_type, occurred_at, payload)"
                " VALUES ('hn', :uid, 'story', :ts, CAST(:p AS jsonb))"
            ),
            {
                "uid": f"{PREFIX}hn-early",
                "ts": SAID_AT,
                "p": (
                    '{"author": "early_bird", "title": "Nobody is talking about verbatimeter '
                    'and termaxa — we are going to need tools that do not trust agents", '
                    '"story_text": ""}'
                ),
            },
        )

        # A usage series so the outcome is measurable: members ×775, peers ×2.1.
        end = FORMED + timedelta(days=90)
        for eid in member_ids:
            for day, value in ((FORMED.date(), 40), (end.date(), 31_000)):
                s.execute(
                    text(
                        "INSERT INTO entity_metrics_daily (entity_id, metric, day, value)"
                        " VALUES (:e, 'pypi_downloads_7d', :d, :v)"
                        " ON CONFLICT (entity_id, metric, day) DO UPDATE SET value = EXCLUDED.value"
                    ),
                    {"e": eid, "d": day, "v": value},
                )
        for i in range(10):
            peer = _entity(s, f"peer-{i}", "agent-framework", f"demo-p{i}", FORMED)
            for day, value in ((FORMED.date(), 100), (end.date(), 210)):
                s.execute(
                    text(
                        "INSERT INTO entity_metrics_daily (entity_id, metric, day, value)"
                        " VALUES (:e, 'pypi_downloads_7d', :d, :v)"
                        " ON CONFLICT (entity_id, metric, day) DO UPDATE SET value = EXCLUDED.value"
                    ),
                    {"e": peer, "d": day, "v": value},
                )

    print(f"seeded {len(MEMBERS)} demo members + 1 early mention + 10 cohort peers")
    print("next: uv run seismo waves --as-of 2026-10-20")


if __name__ == "__main__":
    if "--purge" in sys.argv:
        purge()
    else:
        seed()
