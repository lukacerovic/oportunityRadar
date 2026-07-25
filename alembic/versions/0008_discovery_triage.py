"""continuous discovery triage — discovery_triage_decisions (Feature 6)

Revision ID: 0008
Revises: 0007
Create Date: 2026-07-22

Feature 6 (continuous discovery triage) adds one table. ``discovery_triage_decisions`` is the
audit log of the ``seismo triage`` step: for each freshly-minted discovery entity it records
whether triage decided to keep tracking it (``track``) or to archive it (``skip``), who decided
(``ai`` via the claude_cli LLM, or a deterministic ``threshold``), and the facts the decision was
made on. The ``entity_id UNIQUE`` constraint makes the step idempotent — an entity is triaged at
most once, and re-running naturally skips already-decided entities.

The decision's *effect* (flipping ``entities.tracking_tier`` active → archived) reuses the existing
A-4 bounded-tracking mechanism; this table is the provenance, not a new tracking state.

Additive only — no existing column dropped or rewritten (invariant 1).
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE discovery_triage_decisions (
          id BIGSERIAL PRIMARY KEY,
          entity_id BIGINT NOT NULL UNIQUE REFERENCES entities(id),
          decision TEXT NOT NULL,        -- track | skip
          sector TEXT,
          decided_by TEXT NOT NULL,      -- ai | threshold
          model TEXT,                    -- e.g. claude_cli:opus, null for threshold
          facts JSONB NOT NULL DEFAULT '{}',
          created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS discovery_triage_decisions")
