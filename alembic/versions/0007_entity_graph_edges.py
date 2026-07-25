"""typed entity-graph edges — entity_graph_edges (doc 04, Feature 1)

Revision ID: 0007
Revises: 0006
Create Date: 2026-07-22

Feature 1 (typed entity-graph edges) adds one table. ``entity_graph_edges`` records domain
relations *between* entities — ``built_by`` (person → repo, from GitHub contributors),
``cited`` (repo → paper, from a README's arXiv citation), ``depends_on`` (package → package,
from a PyPI ``requires_dist``). It is deliberately separate from ``entity_links``: that table's
``rule`` column is a resolution-provenance namespace (``attach``, ``R1``..``R6``) read on the
hot path, and mixing domain-relation edges into it would poison those queries. Derived by the
pure ``seismo derive-edges`` pass; each edge carries the raw_event ids that justify it.

Additive only — no existing column dropped or rewritten (invariant 1).
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE entity_graph_edges (
          id BIGSERIAL PRIMARY KEY,
          src_entity_id BIGINT NOT NULL REFERENCES entities(id),
          dst_entity_id BIGINT NOT NULL REFERENCES entities(id),
          edge_type TEXT NOT NULL,              -- built_by | cited | depends_on
          weight REAL NOT NULL DEFAULT 1.0,
          since DATE,
          evidence_refs JSONB NOT NULL DEFAULT '[]',
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          updated_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          UNIQUE (src_entity_id, dst_entity_id, edge_type)
        )
        """
    )
    op.execute("CREATE INDEX ix_graph_edges_dst ON entity_graph_edges (dst_entity_id)")
    op.execute("CREATE INDEX ix_graph_edges_type ON entity_graph_edges (edge_type)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS entity_graph_edges")
