"""memory & synthesis tables — changes_daily + calibration_snapshots (doc 09)

Revision ID: 0005
Revises: 0004
Create Date: 2026-07-11

Stage 8 (Memory & Synthesis, doc 09) adds two tables. ``changes_daily`` holds the deterministic,
templated daily deltas the dashboard Changes view renders (DR-09.1 — no LLM; boring on purpose).
``calibration_snapshots`` is the time series the automated monthly momentum-call review writes
(doc 09 §3) — breakout survival, fade accuracy — trended on the dashboard. ``brief_scores`` (the
quarterly forward-scoring ledger, doc 09 §2) already exists since migration 0001, so the scoring
ritual needs no new table — only the assembler + the A-7 auto-evaluation, which are code.

Additive only — no existing column dropped or rewritten (invariant 1).
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE changes_daily (
          id BIGSERIAL PRIMARY KEY,
          day DATE NOT NULL,
          kind TEXT NOT NULL,              -- new_entity|state_up|state_down|promotion|
                                           -- brief_drafted|brief_published|gate_week
          entity_id BIGINT,                -- null for non-entity rollups (e.g. gate_week)
          text TEXT NOT NULL,              -- the rendered template sentence
          payload JSONB NOT NULL DEFAULT '{}',
          created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute("CREATE INDEX ix_changes_daily_day ON changes_daily (day DESC)")
    op.execute(
        """
        CREATE TABLE calibration_snapshots (
          day DATE NOT NULL,
          metric TEXT NOT NULL,            -- breakout_survival | fade_reaccel
          value NUMERIC,                   -- the ratio, null when the cohort is empty
          sample_n INT NOT NULL DEFAULT 0,
          detail JSONB NOT NULL DEFAULT '{}',
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          PRIMARY KEY (day, metric)
        )
        """
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS calibration_snapshots")
    op.execute("DROP TABLE IF EXISTS changes_daily")
