"""comprehension card status + pack version (doc 05 / doc 13 A-12)

Revision ID: 0003
Revises: 0002
Create Date: 2026-07-11

Doc 13 A-12: an LLM budget-ceiling hit marks the card ``pending`` (call not attempted, retried
next window) — distinct from ``failed`` (reserved for post-retry *validation* errors). ``doctor``
alerts if ``pending`` persists >48h. ``pack_version`` records which evidence-pack builder produced
the card, so cards are reproducible and a pack-builder revision is auditable (doc 05 §2/§6).

Additive only — no existing column dropped or rewritten (invariant 1).
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    # ok = valid card; pending = budget ceiling, no call attempted; failed = validation error
    # after the retry (doc 05 DR-05.2). Existing rows are valid cards, hence default 'ok'.
    op.execute("ALTER TABLE comprehension_cards ADD COLUMN status TEXT NOT NULL DEFAULT 'ok'")
    op.execute("ALTER TABLE comprehension_cards ADD COLUMN pack_version INTEGER")


def downgrade() -> None:
    op.execute("ALTER TABLE comprehension_cards DROP COLUMN IF EXISTS pack_version")
    op.execute("ALTER TABLE comprehension_cards DROP COLUMN IF EXISTS status")
