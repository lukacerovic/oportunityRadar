"""Load the graphify pass's reasoned edges into ``entity_semantic_edges``.

Only ``INFERRED``/``AMBIGUOUS`` edges are imported. ``EXTRACTED`` edges are mechanically
re-derivable from the briefs (and the deterministic ones already live in ``entity_graph_edges``),
so persisting them here would duplicate the spine.

Node ids are resolved back to ``entity_id`` through the brief corpus: a brief's *primary* node id
is ``{parent_dir}_{stem}_{name}``, all normalized. Endpoints that don't match a primary node are
concepts ("Claude Code", "MCP") and land with a NULL entity id but an intact label.

Usage: uv run python scripts/import_semantic_edges.py [--graph graphify-out/graph.json]
                                                      [--briefs briefs] [--model NAME]
"""

from __future__ import annotations

import argparse
import json
import re
from pathlib import Path

from sqlalchemy import text

from seismo.db import session_scope

INFERRED = ("INFERRED", "AMBIGUOUS")


def _norm(s: str) -> str:
    return re.sub(r"_+", "_", re.sub(r"[^a-z0-9]", "_", s.lower())).strip("_")


def primary_node_map(briefs: Path) -> dict[str, int]:
    """Primary node id -> entity_id, read from each brief's frontmatter."""
    out: dict[str, int] = {}
    for f in briefs.rglob("*.md"):
        t = f.read_text(encoding="utf-8")
        eid = re.search(r"^entity_id: (\d+)$", t, re.M)
        name = re.search(r'^name: "(.*)"$', t, re.M)
        if eid and name:
            key = f"{_norm(f.parent.name)}_{_norm(f.stem)}_{_norm(name.group(1))}"
            out[key] = int(eid.group(1))
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--graph", default="graphify-out/graph.json")
    ap.add_argument("--briefs", default="briefs")
    ap.add_argument("--model", default="claude-fable-5:graphify")
    args = ap.parse_args()

    graph = json.loads(Path(args.graph).read_text(encoding="utf-8"))
    resolved = primary_node_map(Path(args.briefs))
    labels = {n["id"]: n.get("label") or n["id"] for n in graph["nodes"]}

    rows = []
    for e in graph["links"]:
        if e.get("confidence") not in INFERRED:
            continue
        src, dst = e["source"], e["target"]
        rows.append(
            {
                "src_entity_id": resolved.get(src),
                "dst_entity_id": resolved.get(dst),
                "src_label": labels.get(src, src),
                "dst_label": labels.get(dst, dst),
                "relation": e["relation"],
                "confidence": e["confidence"],
                "confidence_score": float(e.get("confidence_score") or 0.0),
                "model": args.model,
                "source_file": e.get("source_file"),
            }
        )

    with session_scope() as s:
        s.execute(
            text(
                """
                INSERT INTO entity_semantic_edges
                  (src_entity_id, dst_entity_id, src_label, dst_label, relation,
                   confidence, confidence_score, model, source_file)
                VALUES
                  (:src_entity_id, :dst_entity_id, :src_label, :dst_label, :relation,
                   :confidence, :confidence_score, :model, :source_file)
                ON CONFLICT (src_label, dst_label, relation) DO NOTHING
                """
            ),
            rows,
        )
        s.commit()
        n = s.execute(text("select count(*) from entity_semantic_edges")).scalar()
        both = s.execute(
            text(
                "select count(*) from entity_semantic_edges"
                " where src_entity_id is not null and dst_entity_id is not null"
            )
        ).scalar()

    print(f"imported {len(rows)} edges — table now holds {n} ({both} fully entity-resolved)")


if __name__ == "__main__":
    main()
