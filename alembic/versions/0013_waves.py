"""Wave Radar — convergence detection, observers, outcomes

Revision ID: 0013
Revises: 0012
Create Date: 2026-08-04

Four tables for the convergence layer (``WAVE_PLAN.md``, ``LEAD_TIME_PLAN.md``):

- ``wave_clusters``     one detected convergence: several independent, young entities entering the
                        same problem space inside a short window. Identity is preserved across
                        daily re-runs by member overlap, so a wave keeps its ``first_seen``.
- ``wave_members``      an entity's membership, with the link reason and every independence check
                        (passed and failed) — auditable the way ``gate_decisions`` is.
- ``wave_observations`` the earliest authored, timestamped mentions of a wave's members found in
                        already-collected text, with the lead over detection.
- ``wave_outcomes``     the cohort-relative verdict measured after a horizon: did it take hold.

Additive only — no existing column dropped or rewritten (invariant 1). Nothing here mutates
``raw_events``; observations reference them by id.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE wave_clusters (
          id BIGSERIAL PRIMARY KEY,
          label TEXT,                      -- checkpoint-authored; NULL until named, never required
          label_model TEXT,
          first_seen DATE NOT NULL,        -- earliest member joined_at; never rewritten
          last_active DATE NOT NULL,
          window_days INT NOT NULL,
          strength REAL NOT NULL,
          components JSONB NOT NULL DEFAULT '{}',   -- size/breadth/tightness, like gate components
          merged_into BIGINT REFERENCES wave_clusters(id),
          as_of TIMESTAMPTZ NOT NULL,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute("CREATE INDEX ix_wave_clusters_first_seen ON wave_clusters (first_seen DESC)")

    op.execute(
        """
        CREATE TABLE wave_members (
          id BIGSERIAL PRIMARY KEY,
          wave_id BIGINT NOT NULL REFERENCES wave_clusters(id) ON DELETE CASCADE,
          entity_id BIGINT NOT NULL REFERENCES entities(id),
          joined_at DATE NOT NULL,
          link_reason JSONB NOT NULL DEFAULT '{}',   -- shared neighbour labels that linked it in
          independence JSONB NOT NULL DEFAULT '{}',  -- every check, passed and failed
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          UNIQUE (wave_id, entity_id)
        )
        """
    )
    op.execute("CREATE INDEX ix_wave_members_entity ON wave_members (entity_id)")

    op.execute(
        """
        CREATE TABLE wave_observations (
          id BIGSERIAL PRIMARY KEY,
          wave_id BIGINT NOT NULL REFERENCES wave_clusters(id) ON DELETE CASCADE,
          entity_id BIGINT REFERENCES entities(id),
          raw_event_id BIGINT NOT NULL REFERENCES raw_events(id),
          source TEXT NOT NULL,
          author_handle TEXT,
          observed_at TIMESTAMPTZ NOT NULL,   -- when it was SAID (source time, never ingest time)
          lead_days INT NOT NULL,             -- detection date minus observed_at; may be negative
          excerpt TEXT,
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          UNIQUE (wave_id, raw_event_id)
        )
        """
    )
    op.execute("CREATE INDEX ix_wave_observations_wave ON wave_observations (wave_id, lead_days)")
    op.execute("CREATE INDEX ix_wave_observations_author ON wave_observations (author_handle)")

    op.execute(
        """
        CREATE TABLE wave_outcomes (
          id BIGSERIAL PRIMARY KEY,
          wave_id BIGINT NOT NULL REFERENCES wave_clusters(id) ON DELETE CASCADE,
          evaluated_at TIMESTAMPTZ NOT NULL,
          horizon_days INT NOT NULL,
          metric TEXT NOT NULL,
          wave_growth REAL,                -- median member growth over the horizon
          cohort_growth REAL,              -- median growth of the members' cohorts
          percentile REAL,                 -- wave growth's rank within the cohort distribution
          verdict TEXT NOT NULL,           -- took_hold | flat | faded | unmeasurable
          detail JSONB NOT NULL DEFAULT '{}',
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          UNIQUE (wave_id, horizon_days, metric)
        )
        """
    )
    op.execute("CREATE INDEX ix_wave_outcomes_wave ON wave_outcomes (wave_id)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS wave_outcomes")
    op.execute("DROP TABLE IF EXISTS wave_observations")
    op.execute("DROP TABLE IF EXISTS wave_members")
    op.execute("DROP TABLE IF EXISTS wave_clusters")
