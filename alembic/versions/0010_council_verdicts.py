"""Council review — council_verdicts (doc 08 §5)

Revision ID: 0010
Revises: 0009
Create Date: 2026-07-25

Adds one table for the council-review checkpoint: three independent LLM perspectives
(``skeptic``, ``evidence_auditor``, ``mechanism_reviewer``) each deliberate separately on an
already-drafted ``ImpactBrief`` and record a stance (``adopt``/``watch``/``reject``). Deliberately
three *separate* rows per brief, not one synthesized verdict — the aggregate (majority vote) is
computed on read, never stored, so the individual dissent is never lost to a summary.

Expensive by design (3 LLM calls per brief), so it is scoped to a small top-N population
(``seismo council --top N``, ranked by momentum/velocity percentile, independent of the weekly
significance gate) and never run from ``daily.sh``.

Additive only — no existing column dropped or rewritten (invariant 1).
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE council_verdicts (
          id BIGSERIAL PRIMARY KEY,
          entity_id BIGINT NOT NULL REFERENCES entities(id),
          impact_brief_id BIGINT NOT NULL REFERENCES impact_briefs(id),
          role TEXT NOT NULL,              -- skeptic | evidence_auditor | mechanism_reviewer
          stance TEXT NOT NULL,            -- adopt | watch | reject
          confidence TEXT NOT NULL,        -- low | med | high
          reasoning TEXT NOT NULL,
          model TEXT NOT NULL,
          cost_usd NUMERIC(8,4) NOT NULL DEFAULT 0,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          UNIQUE (impact_brief_id, role)
        )
        """
    )
    op.execute("CREATE INDEX ix_council_verdicts_entity ON council_verdicts (entity_id)")
    op.execute(
        "CREATE INDEX ix_council_verdicts_brief ON council_verdicts (impact_brief_id)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS council_verdicts")
