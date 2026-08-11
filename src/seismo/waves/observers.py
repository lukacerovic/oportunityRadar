"""Early observers — who mentioned a wave's members before the system detected the wave.

The claim this produces is a date, not an opinion: *this was discussed N days before we flagged it*.
A date is falsifiable without market data and without confounders, which is why it is the first
thing built and the last thing to be argued about.

**Source discipline.** A source is usable here only if it carries an author *and* a source-time
timestamp. That rules out most of the corpus, and the exclusions are deliberate rather than
incidental:

- READMEs, model cards, arXiv abstracts — artifacts. They record what was built, not who understood
  it first, and their text has no author attached at the granularity we would need.
- ``hn_discussion`` enrichment events — excluded **as the collector writes them today**, not
  because the source lacks the data. ``_top_comments`` (``collectors/launches.py``) keeps only
  ``child["text"]`` and joins twelve comments into one blob under a single ``now()`` stamp, so a
  lead computed from it would be measured against fetch time — confident and meaningless, the exact
  failure this feature exists to avoid. **The API does return ``author``, ``created_at`` and
  ``points`` per comment** (verified live, ``TIME_METADATA_AUDIT.md`` 2026-08-05). Fixing the
  collector to emit one event per comment removes this exclusion and is the single largest
  expansion available to the lead-time corpus.
- download counts, star counts, token counts — no author, no opinion. They grade an observer
  (``waves/outcomes.py``); they can never identify one.

That leaves ``hn``/``story`` today. Substack is approved in ``DECISIONS.md`` and unbuilt; the
``community/`` layer is built and has never been run. Both drop straight into ``_SOURCES`` when they
land, which is why this is a registry rather than a hard-coded query.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import UTC, datetime

from sqlalchemy import text
from sqlalchemy.orm import Session

# Terms shorter than this are not searched: a three-letter repo name matches half of Hacker News,
# and a false "earliest mention" is worse than no mention at all — it back-dates the record.
MIN_TERM_LEN = 4
EXCERPT_CHARS = 280
MAX_PER_MEMBER = 3


@dataclass(frozen=True)
class SourceSpec:
    """One usable observation surface. ``author_key`` and ``text_keys`` are payload keys."""

    source: str
    event_type: str
    author_key: str
    text_keys: tuple[str, ...]


_SOURCES: tuple[SourceSpec, ...] = (
    # Algolia HN hits are stored verbatim, so 'author' is the poster and occurred_at came from
    # created_at_i — real source time. This is currently the only surface that satisfies both.
    SourceSpec("hn", "story", "author", ("title", "story_text", "comment_text")),
)


def search_terms(canonical_name: str, github_anchor: str | None) -> list[str]:
    """Distinctive strings that identify an entity in free text.

    The repo name is taken without its owner (``acme/termaxa`` -> ``termaxa``) because that is how
    people refer to a project in prose, and the owner prefix would prevent every real match."""
    terms: set[str] = set()
    for raw in (canonical_name, (github_anchor or "").split("/")[-1]):
        term = (raw or "").strip().lower()
        if len(term) >= MIN_TERM_LEN:
            terms.add(term)
    return sorted(terms)


def _members(session: Session, wave_id: int) -> list[tuple[int, str, str | None]]:
    rows = session.execute(
        text(
            """
            SELECT e.id, e.canonical_name, e.attrs -> 'anchors' ->> 'github' AS gh
            FROM wave_members m JOIN entities e ON e.id = m.entity_id
            WHERE m.wave_id = :wave_id
            """
        ),
        {"wave_id": wave_id},
    ).all()
    return [(r[0], r[1], r[2]) for r in rows]


def find_for_wave(session: Session, wave_id: int, as_of: datetime | None = None) -> int:
    """Record the earliest authored mentions of a wave's members. Returns rows written.

    Only events at or before ``as_of`` are read (invariant 2), so replaying a past day cannot pull
    in a mention that had not been published yet."""
    as_of = as_of or datetime.now(UTC)
    detected = session.execute(
        text("SELECT first_seen FROM wave_clusters WHERE id = :id"), {"id": wave_id}
    ).scalar()
    if detected is None:
        return 0

    written = 0
    for entity_id, name, gh in _members(session, wave_id):
        terms = search_terms(name, gh)
        if not terms:
            continue
        for spec in _SOURCES:
            # Word-boundary regex, not ILIKE '%term%': 'r3' inside 'chair3d' is not a mention, and
            # substring matching would quietly fill the record with noise that reads as foresight.
            pattern = "|".join(rf"\m{re.escape(t)}\M" for t in terms)
            rows = session.execute(
                text(
                    f"""
                    SELECT id, occurred_at, payload ->> :author_key AS author,
                           concat_ws(' ', {", ".join(f"payload ->> '{k}'" for k in spec.text_keys)})
                             AS body
                    FROM raw_events
                    WHERE source = :source AND event_type = :event_type
                      AND occurred_at <= :as_of
                      AND concat_ws(' ', {", ".join(f"payload ->> '{k}'" for k in spec.text_keys)})
                          ~* :pattern
                    ORDER BY occurred_at ASC
                    LIMIT :limit
                    """  # noqa: S608 — text_keys come from the module-level registry, never input
                ),
                {
                    "author_key": spec.author_key,
                    "source": spec.source,
                    "event_type": spec.event_type,
                    "as_of": as_of,
                    "pattern": pattern,
                    "limit": MAX_PER_MEMBER,
                },
            ).mappings()

            for r in rows:
                observed = r["occurred_at"]
                lead = (detected - observed.date()).days
                # RETURNING + rowcount, so the reported total is rows actually written. One story
                # can mention several members of the same wave, and the UNIQUE constraint collapses
                # those into one row — counting attempts would overstate the record's size.
                inserted = session.execute(
                    text(
                        """
                        INSERT INTO wave_observations
                          (wave_id, entity_id, raw_event_id, source, author_handle,
                           observed_at, lead_days, excerpt)
                        VALUES (:wave_id, :entity_id, :raw_event_id, :source, :author,
                                :observed_at, :lead_days, :excerpt)
                        ON CONFLICT (wave_id, raw_event_id) DO NOTHING
                        RETURNING id
                        """
                    ),
                    {
                        "wave_id": wave_id,
                        "entity_id": entity_id,
                        "raw_event_id": r["id"],
                        "source": spec.source,
                        "author": r["author"],
                        "observed_at": observed,
                        "lead_days": lead,
                        "excerpt": (r["body"] or "")[:EXCERPT_CHARS],
                    },
                )
                written += len(inserted.fetchall())
    return written


def run_observers(session: Session, as_of: datetime | None = None) -> dict[str, int]:
    """Find early observations for every live wave."""
    as_of = as_of or datetime.now(UTC)
    wave_ids = list(
        session.execute(
            text("SELECT id FROM wave_clusters WHERE merged_into IS NULL ORDER BY id")
        ).scalars()
    )
    total = sum(find_for_wave(session, wid, as_of) for wid in wave_ids)
    return {"waves": len(wave_ids), "observations": total}
