"""community research layer

Revision ID: 0011
Revises: 0010
Create Date: 2026-07-24

Stores refreshable community-opinion analysis for existing entities. v1 sources are GitHub issues/discussions, Hugging Face model
discussions, and Hacker News.
Rows are append-only so the latest projection is cheap while historical community changes remain
auditable.
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE entity_community_research (
          id BIGSERIAL PRIMARY KEY,
          entity_id BIGINT NOT NULL REFERENCES entities(id),
          source TEXT NOT NULL,
          status TEXT NOT NULL,
          query_set JSONB NOT NULL,
          result JSONB NOT NULL,
          model TEXT,
          researched_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          created_at TIMESTAMPTZ NOT NULL DEFAULT now()
        )
        """
    )
    op.execute(
        "CREATE INDEX ix_entity_community_research_entity_source "
        "ON entity_community_research (entity_id, source, researched_at DESC)"
    )
    op.execute(
        "CREATE INDEX ix_entity_community_research_status "
        "ON entity_community_research (status)"
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS entity_community_research")
