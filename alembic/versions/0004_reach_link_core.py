"""reach_links.core flag (doc 07 §2 / doc 08 §1 / doc 13 A-1)

Revision ID: 0004
Revises: 0003
Create Date: 2026-07-11

The significance gate (doc 07 §2) sets Reach R = 1.0 when an entity's category touches >=3
mapped revenue lines *or* any line flagged ``core`` (a critical dependency). ``reach_links`` is the
derived index the gate reads, so it must carry the ``core`` flag from the company YAML's
``threat_surface[].core`` — otherwise the gate would have to re-open the JSONB doc per candidate.
Derived data: ``seismo load-map`` rebuilds these rows from ``exposure_map/*.yaml`` on every load.

Additive only — no existing column dropped or rewritten (invariant 1).
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE reach_links ADD COLUMN core BOOLEAN NOT NULL DEFAULT false")


def downgrade() -> None:
    op.execute("ALTER TABLE reach_links DROP COLUMN IF EXISTS core")
