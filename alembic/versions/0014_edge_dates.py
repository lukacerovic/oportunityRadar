"""Employment timeline on graph edges — start_date/end_date

Revision ID: 0014
Revises: 0013
Create Date: 2026-07-28

Wikidata employer claims carry P580/P582 qualifiers; until now derive-edges kept them only in
the raw payload. Two nullable DATE columns on ``entity_graph_edges`` put the timeline on the
edge itself ("employed_by OpenAI 2018–2024"), where the API and the ✨ narration can read it.

Additive only — no existing column dropped or rewritten (invariant 1).
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0014"
down_revision: str | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("ALTER TABLE entity_graph_edges ADD COLUMN start_date DATE")
    op.execute("ALTER TABLE entity_graph_edges ADD COLUMN end_date DATE")


def downgrade() -> None:
    op.execute("ALTER TABLE entity_graph_edges DROP COLUMN IF EXISTS start_date")
    op.execute("ALTER TABLE entity_graph_edges DROP COLUMN IF EXISTS end_date")
