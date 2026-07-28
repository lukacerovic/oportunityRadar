"""``seismo explain-graphs`` — AI-narrated context for an entity's relationship subgraph.

The graph page can SHOW that Mira Murati founded Thinking Machines Lab and used to work at
OpenAI; this layer explains it: who each person is, which relationship brought them into the
graph, how the organizations relate to each other, and what the team pedigree signals about the
project. The narration is written from ONLY the facts in the subgraph (nodes, typed edges, the
Wikidata display cards) — the prompt forbids outside knowledge, so every claim is traceable to
an edge the reader can see.

Change-driven regeneration: ``subgraph_hash`` fingerprints the exact facts the text was written
about. The daily step walks the top trending entities, recomputes each hash, and calls the LLM
only where the hash differs from the stored row — new enrichment triggers a rewrite, an
unchanged graph costs nothing. Runs on ``graph_explain_provider`` (claude_cli here — narrative
synthesis is where the local 3B model is weakest).
"""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from sqlalchemy import text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from seismo.checkpoints.llm import complete_graph_explanation
from seismo.models import GraphExplanation

# Explanations narrate a FOCUSED neighborhood. Above this many nodes the pack is truncated to
# the highest-degree ones and the prompt says so — narrating 2,000 contributors is noise.
MAX_PACK_NODES = 60

SECTIONS = ("overview", "key_people", "organizations", "industry_context", "signals")

EXPLANATION_SCHEMA: dict[str, Any] = {
    "type": "object",
    "properties": {
        "overview": {
            "type": "string",
            "description": "2-4 sentences: what this graph is about and the single most "
            "important thing it shows.",
        },
        "key_people": {
            "type": "string",
            "description": "Markdown. For each person that matters: who they are (from their "
            "description/positions), WHICH relationship brought them into this graph, and "
            "their notable works if listed. Skip long tails of minor contributors.",
        },
        "organizations": {
            "type": "string",
            "description": "Markdown. How each organization relates to the focus entity — e.g. "
            "'OpenAI appears as the founder's previous employer (2018-2024), not as a partner'. "
            "Cover ownership/investor/subsidiary links when present.",
        },
        "industry_context": {
            "type": "string",
            "description": "Markdown. The ONE section where widely-known background is allowed: "
            "what the organizations in this graph actually build, and how the focus compares to "
            "the orgs its people came from (similarities, differences, technology focus — e.g. "
            "OpenAI vs the focus company). Stick to entities present in the graph; open with "
            "'(industry knowledge, not from the graph)'.",
        },
        "signals": {
            "type": "string",
            "description": "Markdown bullets. What the relationships imply about the project's "
            "potential (team pedigree, backing, lineage). Only claims supported by the listed "
            "facts; say what is NOT known.",
        },
    },
    "required": list(SECTIONS),
}

_SYSTEM = """You explain relationship graphs from a tech-intelligence tool. The user is looking
at a graph centered on one entity (a model, repo, paper, org, or person) and needs to understand
who everyone is and why they are connected.

STRICT RULES:
- In overview/key_people/organizations/signals: use ONLY the facts provided (nodes, edges,
  profile details). You may add widely-known context ONLY to identify something already in the
  graph (e.g. that ChatGPT is an OpenAI product), never to introduce new relationships.
- industry_context is the ONE exception: there you may use widely-known background about the
  entities in the graph — what they build, how the focus org/project compares to the orgs its
  people came from (technology focus, positioning, similarities and differences). Never invent
  relationships between graph entities beyond the listed edges, and keep it about entities that
  appear in this graph.
- For every person/org you mention, tie it to the specific edge that puts it in the graph.
- Edge meanings: employed_by=current employer claim; formerly_at=past employer (has end date);
  founded=founded the org; developed_by=model published under the org's account;
  authored_by=paper author; built_by=repo contributor; educated_at=studied there;
  advised_by=doctoral advisor; notable_work=famous for building it; subsidiary_of/owned_by/
  invested_in=corporate structure and backing.
- Be direct about limits: if the graph shows a connection but not its nature, say so.
- Plain language, no hype. Write for an investor scanning for signal."""


@dataclass
class Subgraph:
    focus_id: int
    focus_name: str
    nodes: list[dict[str, Any]] = field(default_factory=list)  # {id,name,type,info}
    edges: list[tuple[str, str, str]] = field(default_factory=list)  # (src_name, type, dst_name)
    truncated_from: int = 0  # original node count when capped, else 0

    @property
    def hash(self) -> str:
        basis = json.dumps(
            {
                "nodes": sorted((n["name"], n["type"]) for n in self.nodes),
                "edges": sorted(self.edges),
            },
            sort_keys=True,
        )
        return hashlib.sha256(basis.encode()).hexdigest()


def build_subgraph(session: Session, entity_id: int) -> Subgraph | None:
    """The 2-hop neighborhood the graph page shows for a focus entity: the entity, everything
    one edge away, and the edges among that set (so a hop-1 person's employers are included)."""
    focus = session.execute(
        text(
            "SELECT canonical_name FROM entities WHERE id = :id AND merged_into IS NULL"
        ),
        {"id": entity_id},
    ).scalar()
    if focus is None:
        return None

    # Person-mediated expansion, so the pack matches what the page shows instead of crawling
    # institutional trees. From the focus we always expand; after that we expand only through
    # PEOPLE (their careers, schools, notable works) — and through a hop-1 org exactly when the
    # focus is an artifact (model → publisher org → its team). Expanding through every org would
    # drag in Goldman's CEO history and a school's sibling campuses: the "institutional filler"
    # that bloated early narrations to 160 nodes while the page showed 22.
    focus_type = session.execute(
        text("SELECT entity_type FROM entities WHERE id = :id"), {"id": entity_id}
    ).scalar()
    artifact_focus = focus_type in {"model", "project", "paper", "product"}

    focus_set: set[int] = {entity_id}
    types: dict[int, str] = {entity_id: str(focus_type)}
    frontier: set[int] = {entity_id}
    for round_no in range(3):
        expand_from = [
            n
            for n in frontier
            if n == entity_id
            or types.get(n) == "person"
            or (types.get(n) == "org" and artifact_focus and round_no == 1)
        ]
        if not expand_from:
            break
        neighbor_rows = session.execute(
            text(
                """
                SELECT DISTINCT e.id, e.entity_type
                FROM entity_graph_edges ge
                JOIN entities e ON e.id = CASE
                    WHEN ge.src_entity_id = ANY(:f) THEN ge.dst_entity_id
                    ELSE ge.src_entity_id END
                WHERE ge.src_entity_id = ANY(:f) OR ge.dst_entity_id = ANY(:f)
                """
            ),
            {"f": expand_from},
        ).all()
        frontier = {int(nid) for nid, _ in neighbor_rows} - focus_set
        for nid, etype in neighbor_rows:
            types[int(nid)] = str(etype)
        focus_set |= frontier
    rows = session.execute(
        text(
            """
            SELECT ge.edge_type,
                   e1.id AS src_id, e1.canonical_name AS src_name, e1.entity_type AS src_type,
                   e1.attrs->'wikidata' AS src_info,
                   e2.id AS dst_id, e2.canonical_name AS dst_name, e2.entity_type AS dst_type,
                   e2.attrs->'wikidata' AS dst_info
            FROM entity_graph_edges ge
            JOIN entities e1 ON e1.id = ge.src_entity_id
            JOIN entities e2 ON e2.id = ge.dst_entity_id
            WHERE ge.src_entity_id = ANY(:ids) OR ge.dst_entity_id = ANY(:ids)
            """
        ),
        {"ids": list(focus_set)},
    ).mappings()

    nodes: dict[int, dict[str, Any]] = {}
    degree: dict[int, int] = {}
    edges: list[tuple[int, str, int]] = []
    for r in rows:
        # Interior edges only — an OpenAI board member is NOT in the set (OpenAI was reached
        # through a person, and orgs beyond hop 1 don't expand), so their edge is dropped even
        # though it touches OpenAI. The pack narrates exactly the picture on screen.
        if r["src_id"] not in focus_set or r["dst_id"] not in focus_set:
            continue
        for side in ("src", "dst"):
            nid = r[f"{side}_id"]
            nodes.setdefault(
                nid,
                {
                    "id": nid,
                    "name": r[f"{side}_name"],
                    "type": r[f"{side}_type"],
                    "info": r[f"{side}_info"],
                },
            )
            degree[nid] = degree.get(nid, 0) + 1
        edges.append((r["src_id"], r["edge_type"], r["dst_id"]))

    sub = Subgraph(focus_id=entity_id, focus_name=str(focus))
    if not edges:
        return sub  # nothing to narrate — caller skips

    kept_ids = set(nodes)
    if len(nodes) > MAX_PACK_NODES:
        sub.truncated_from = len(nodes)
        ranked = sorted(nodes, key=lambda n: degree.get(n, 0), reverse=True)
        kept_ids = set(ranked[:MAX_PACK_NODES]) | {entity_id}

    sub.nodes = [nodes[n] for n in sorted(kept_ids) if n in nodes]
    name_of = {n: nodes[n]["name"] for n in nodes}
    sub.edges = [
        (name_of[s], et, name_of[d])
        for s, et, d in edges
        if s in kept_ids and d in kept_ids
    ]
    return sub


def evidence_pack(sub: Subgraph) -> str:
    """The facts, serialized for the prompt — nothing the model sees comes from anywhere else."""
    lines = [f"FOCUS ENTITY: {sub.focus_name}", "", "NODES:"]
    for n in sub.nodes:
        parts = [f"- {n['name']} ({n['type']}"]
        info = n.get("info") or {}
        if info.get("description"):
            parts.append(f"; {info['description']}")
        if info.get("positions"):
            parts.append(f"; positions: {', '.join(info['positions'][:4])}")
        if info.get("inception"):
            parts.append(f"; founded {info['inception']}")
        if info.get("headquarters"):
            parts.append(f"; HQ {', '.join(info['headquarters'][:2])}")
        if info.get("revenue"):
            parts.append(f"; revenue {info['revenue']}")
        if info.get("market_cap"):
            parts.append(f"; market cap {info['market_cap']}")
        if info.get("license"):
            parts.append(f"; license {', '.join(info['license'][:2])}")
        if info.get("awards"):
            parts.append(f"; awards: {', '.join(info['awards'][:3])}")
        parts.append(")")
        if info.get("wiki"):
            parts.append(f"\n  background: {str(info['wiki'])[:350]}")
        lines.append("".join(parts))
    lines += ["", "RELATIONSHIPS:"]
    lines += [f"- {s} --{et}--> {d}" for s, et, d in sorted(sub.edges)]
    if sub.truncated_from:
        lines.append(
            f"\nNOTE: view truncated to the {len(sub.nodes)} most-connected of "
            f"{sub.truncated_from} nodes."
        )
    return "\n".join(lines)


def _fallback(sub: Subgraph) -> dict[str, str]:
    """Deterministic mock-provider content — also the shape real providers must match."""
    people = sum(1 for n in sub.nodes if n["type"] == "person")
    orgs = sum(1 for n in sub.nodes if n["type"] == "org")
    return {
        "overview": (
            f"Graph around {sub.focus_name}: {len(sub.nodes)} entities "
            f"({people} people, {orgs} organizations) and {len(sub.edges)} relationships."
        ),
        "key_people": "(mock provider — no narration)",
        "organizations": "(mock provider — no narration)",
        "industry_context": "(mock provider — no narration)",
        "signals": "(mock provider — no narration)",
    }


@dataclass
class ExplainStats:
    candidates: int = 0
    generated: int = 0
    unchanged: int = 0
    skipped_empty: int = 0
    failed: int = 0
    cost_usd: float = 0.0

    def as_note(self) -> str:
        return (
            f"candidates={self.candidates} generated={self.generated} "
            f"unchanged={self.unchanged} empty={self.skipped_empty} failed={self.failed} "
            f"cost=${self.cost_usd:.4f}"
        )


def explain_entity(
    session: Session, entity_id: int, *, force: bool = False
) -> tuple[str, float]:
    """Generate/refresh one entity's explanation. Returns ('generated'|'unchanged'|'empty',
    cost_usd). Raises on LLM failure (strict — a fallback row would read like a real one)."""
    sub = build_subgraph(session, entity_id)
    if sub is None or not sub.edges:
        return "empty", 0.0
    stored = session.execute(
        text("SELECT subgraph_hash FROM graph_explanations WHERE entity_id = :id"),
        {"id": entity_id},
    ).scalar()
    if stored == sub.hash and not force:
        return "unchanged", 0.0

    result = complete_graph_explanation(
        _SYSTEM,
        evidence_pack(sub),
        EXPLANATION_SCHEMA,
        fallback=_fallback(sub),
    )
    content = {k: str(result.content.get(k, "")) for k in SECTIONS}
    stmt = pg_insert(GraphExplanation).values(
        entity_id=entity_id,
        subgraph_hash=sub.hash,
        content=content,
        model=result.model,
        cost_usd=result.cost_usd,
        node_count=len(sub.nodes),
        edge_count=len(sub.edges),
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=["entity_id"],
        set_={
            "subgraph_hash": stmt.excluded.subgraph_hash,
            "content": stmt.excluded.content,
            "model": stmt.excluded.model,
            "cost_usd": stmt.excluded.cost_usd,
            "node_count": stmt.excluded.node_count,
            "edge_count": stmt.excluded.edge_count,
            "updated_at": datetime.now(UTC),
        },
    )
    session.execute(stmt)
    return "generated", float(result.cost_usd)


def select_targets(session: Session, *, limit: int) -> list[int]:
    """Entities worth narrating, best-first: the same top-trending ranking the graph page uses
    (gate-passed first, then momentum score), restricted to entities that HAVE relationships."""
    return list(
        session.execute(
            text(
                """
                WITH ms AS (
                    SELECT DISTINCT ON (entity_id) entity_id, state, score
                    FROM momentum_states ORDER BY entity_id, day DESC
                ),
                gp AS (SELECT DISTINCT entity_id FROM gate_decisions WHERE decision = 'pass')
                SELECT e.id FROM entities e
                LEFT JOIN ms ON ms.entity_id = e.id
                LEFT JOIN gp ON gp.entity_id = e.id
                WHERE e.merged_into IS NULL
                  AND (gp.entity_id IS NOT NULL OR ms.state IN ('breakout', 'accelerating'))
                  AND EXISTS (SELECT 1 FROM entity_graph_edges ge
                              WHERE ge.src_entity_id = e.id OR ge.dst_entity_id = e.id)
                ORDER BY (gp.entity_id IS NOT NULL) DESC, ms.score DESC NULLS LAST, e.id
                LIMIT :limit
                """
            ),
            {"limit": limit},
        )
        .scalars()
        .all()
    )


def run_explain(session: Session, *, limit: int = 10, force: bool = False) -> ExplainStats:
    """Walk the top trending entities; regenerate only where the subgraph changed."""
    stats = ExplainStats()
    for entity_id in select_targets(session, limit=limit):
        stats.candidates += 1
        try:
            outcome, cost = explain_entity(session, entity_id, force=force)
        except Exception:  # noqa: BLE001 — one bad generation must not kill the batch
            stats.failed += 1
            continue
        stats.cost_usd += cost
        if outcome == "generated":
            stats.generated += 1
        elif outcome == "unchanged":
            stats.unchanged += 1
        else:
            stats.skipped_empty += 1
    return stats
