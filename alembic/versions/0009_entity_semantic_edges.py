"""LLM-inferred semantic edges — entity_semantic_edges

Revision ID: 0009
Revises: 0008
Create Date: 2026-07-25

Holds the *reasoned* relations a comprehension pass proposes between entities —
``semantically_similar_to`` (two projects solve the same problem with no structural link),
``conceptually_related_to``, and named references to concepts the graph pass surfaced.

Deliberately NOT ``entity_graph_edges``: that table is the deterministic spine, every row
justified by raw_event ids from the pure ``derive-edges`` pass (invariant 4 — collectors never
reason). Rows here are a model's judgement and carry ``model`` + ``confidence_score`` so a
consumer can always ask for rule-derived only, or opt into inference explicitly.

Endpoints are nullable: an edge may point at a concept node ("Claude Code", "MCP") that is not a
tracked entity. ``src_label``/``dst_label`` are always populated, so a concept-anchored edge is
preserved rather than dropped.

Additive only — no existing column dropped or rewritten (invariant 1).
"""

from __future__ import annotations

from collections.abc import Sequence

from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute(
        """
        CREATE TABLE entity_semantic_edges (
          id BIGSERIAL PRIMARY KEY,
          src_entity_id BIGINT REFERENCES entities(id),   -- NULL when the endpoint is a concept
          dst_entity_id BIGINT REFERENCES entities(id),
          src_label TEXT NOT NULL,
          dst_label TEXT NOT NULL,
          relation TEXT NOT NULL,          -- semantically_similar_to | conceptually_related_to
          confidence TEXT NOT NULL,        -- INFERRED | AMBIGUOUS (EXTRACTED belongs in the spine)
          confidence_score REAL NOT NULL,
          model TEXT NOT NULL,             -- which model authored the judgement
          source_file TEXT,                -- brief the edge was reasoned from
          created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
          UNIQUE (src_label, dst_label, relation)
        )
        """
    )
    op.execute("CREATE INDEX ix_semantic_edges_src ON entity_semantic_edges (src_entity_id)")
    op.execute("CREATE INDEX ix_semantic_edges_dst ON entity_semantic_edges (dst_entity_id)")
    op.execute("CREATE INDEX ix_semantic_edges_relation ON entity_semantic_edges (relation)")


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS entity_semantic_edges")
