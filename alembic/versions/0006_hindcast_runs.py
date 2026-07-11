"""hindcast validation ledger — hindcast_runs (doc 11 §4)

Revision ID: 0006
Revises: 0005
Create Date: 2026-07-11

Stage 9 (Validation & Hindcast, doc 11) adds one table. ``hindcast_runs`` records each execution
of a pinned case (DeepSeek, Reflection-70B, …) — its window, the pinned brief ``as_of``, the pass/
fail tally, the per-assertion results (JSONB), and the rendered markdown trace report. It is the
permanent record that the production pipeline, run over backfilled history, still reproduces the
foreshock it was built to catch (DR-11.2). Re-running a case appends a new row (history is kept).

Additive only — no existing column dropped or rewritten (invariant 1).
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE hindcast_runs (
          id BIGSERIAL PRIMARY KEY,
          case_name TEXT NOT NULL,
          window_from DATE NOT NULL,
          window_to DATE NOT NULL,
          brief_as_of TIMESTAMPTZ,          -- the pinned H2 instant; null for brief-free cases
          passed BOOLEAN NOT NULL,          -- every assertion green
          total INT NOT NULL DEFAULT 0,
          failed INT NOT NULL DEFAULT 0,
          results JSONB NOT NULL DEFAULT '[]',  -- per-assertion {id,type,passed,detail}
          report TEXT,                      -- the rendered markdown trace (PMG-demo artifact)
          created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute("CREATE INDEX ix_hindcast_runs_case ON hindcast_runs (case_name, created_at DESC)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS hindcast_runs")
