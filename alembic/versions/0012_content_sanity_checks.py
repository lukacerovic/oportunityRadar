"""Content sanity checkpoint — content_sanity_checks

Revision ID: 0012
Revises: 0011
Create Date: 2026-07-26

Adds one table for the content-sanity checkpoint: an LLM judges whether a freshly-collected raw
event's free text (README, model card, launch page, HN discussion, paper abstract) is legible,
on-topic, substantive content, and may propose a cosmetically-cleaned version for display. Never
mutates ``raw_events`` (doc 02 §1: raw events are immutable) — a 'reject' verdict just means "don't
feature this text", recorded as a separate row, never a delete or edit of the source event.

One row per raw_event (UNIQUE), so re-running the checkpoint only checks newly-collected events.

Additive only — no existing column dropped or rewritten (invariant 1).
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE content_sanity_checks (
          id BIGSERIAL PRIMARY KEY,
          raw_event_id BIGINT NOT NULL REFERENCES raw_events(id),
          verdict TEXT NOT NULL,           -- ok | flagged | reject
          reasoning TEXT NOT NULL,
          cleaned_text TEXT,               -- cosmetically-cleaned display text, when proposed
          model TEXT NOT NULL,
          cost_usd NUMERIC(8,4) NOT NULL DEFAULT 0,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          UNIQUE (raw_event_id)
        )
        """
    )
    op.execute(
        "CREATE INDEX ix_content_sanity_checks_raw_event ON content_sanity_checks (raw_event_id)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS content_sanity_checks")
