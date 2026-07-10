"""as-of correct entity graph + bounded tracking (doc 13 A-2 + A-4)

Revision ID: 0002
Revises: 0001
Create Date: 2026-07-11

Doc 04 / doc 13 A-2: the entity graph must be **as-of correct** or every hindcast leaks
future knowledge. Merges become their own time-versioned table (``entity_merges``) keyed on
``justified_at`` = MAX(occurred_at) of the supporting evidence; ``entities.merged_into`` stays
only as a convenience denormalization that as-of code never reads. Links carry the
``occurred_at`` of their justifying event; category is time-versioned (it drives cohorts);
theme assignments carry ``effective_at``. A-4 adds the ``tracking_tier`` lifecycle columns.

Additive only — no existing column is dropped or rewritten (invariant 1).
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # --- A-2: as-of correct entity graph ---
    # Every link records the occurred_at of the event that justifies it, so the graph can be
    # rebuilt "as it was known" at any past instant. NULL only for links with no single event.
    op.execute("ALTER TABLE entity_links ADD COLUMN evidence_occurred_at TIMESTAMPTZ")

    # Merges are their own append-only, reversible record. justified_at = MAX(occurred_at) of the
    # supporting evidence; a merge is visible at as_of only when active AND justified_at <= as_of.
    op.execute(
        """
        CREATE TABLE entity_merges (
          loser_id BIGINT PRIMARY KEY REFERENCES entities(id),
          survivor_id BIGINT NOT NULL REFERENCES entities(id),
          justified_at TIMESTAMPTZ NOT NULL,
          rule TEXT NOT NULL,
          confidence REAL NOT NULL,
          decided_by TEXT NOT NULL,
          decided_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          active BOOLEAN NOT NULL DEFAULT true,
          CHECK (loser_id <> survivor_id)
        )
        """
    )
    op.execute("CREATE INDEX ix_entity_merges_survivor ON entity_merges (survivor_id) WHERE active")

    # Category is time-versioned because it drives cohorts (doc 06) and reach (doc 07): the
    # category an entity had *at as_of* must be recoverable, not just its category today.
    op.execute(
        """
        CREATE TABLE entity_category_history (
          id BIGSERIAL PRIMARY KEY,
          entity_id BIGINT NOT NULL REFERENCES entities(id),
          category TEXT NOT NULL,
          effective_at TIMESTAMPTZ NOT NULL,
          evidence_event BIGINT REFERENCES raw_events(id),
          created_at TIMESTAMPTZ DEFAULT now()
        )
        """
    )
    op.execute(
        "CREATE INDEX ix_entity_category_history_lookup "
        "ON entity_category_history (entity_id, effective_at)"
    )

    op.execute("ALTER TABLE entity_themes ADD COLUMN effective_at TIMESTAMPTZ")

    # --- A-4: bounded tracking set ---
    op.execute("ALTER TABLE entities ADD COLUMN tracking_tier TEXT NOT NULL DEFAULT 'active'")
    op.execute("ALTER TABLE entities ADD COLUMN tier_reviewed_at TIMESTAMPTZ")


def downgrade() -> None:
    op.execute("ALTER TABLE entities DROP COLUMN IF EXISTS tier_reviewed_at")
    op.execute("ALTER TABLE entities DROP COLUMN IF EXISTS tracking_tier")
    op.execute("ALTER TABLE entity_themes DROP COLUMN IF EXISTS effective_at")
    op.execute("DROP TABLE IF EXISTS entity_category_history CASCADE")
    op.execute("DROP TABLE IF EXISTS entity_merges CASCADE")
    op.execute("ALTER TABLE entity_links DROP COLUMN IF EXISTS evidence_occurred_at")
