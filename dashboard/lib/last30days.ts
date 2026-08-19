import fs from "node:fs";
import path from "node:path";
import type { GraphResponse, GraphNode, GraphEdge } from "@/lib/types";

// The last30days briefs are an EXTERNAL, manually-run research corpus — they never enter Postgres
// (social/video content has no reliable occurred_at, see LAST30DAYS_RUNBOOK.md). So this screen
// reads the graphify build straight off disk instead of going through the API: no DB, no route,
// no invariant to break. Regenerate the graph and refresh the page.
const GRAPH_PATH = path.join(
  process.cwd(),
  "..",
  "research",
  "last30days",
  "graphify-out",
  "graph.json"
);
const LABELS_PATH = path.join(
  process.cwd(),
  "..",
  "research",
  "last30days",
  "graphify-out",
  ".graphify_labels.json"
);

interface GraphifyNode {
  id: string;
  label: string;
  file_type?: string;
  community?: number;
  source_file?: string | null;
}
interface GraphifyLink {
  source: string;
  target: string;
  relation?: string;
  confidence?: string;
  confidence_score?: number;
  weight?: number;
}

// graphify's file_type is the honest node taxonomy for a discussion corpus: what a thing IS
// (product/repo/company), what someone CLAIMED, and WHERE it was said. Map it onto the dashboard's
// category slot so the existing category-hashed palette colors them apart for free.
const KIND_BY_FILE_TYPE: Record<string, string> = {
  concept: "entity",
  rationale: "claim",
  document: "source",
};

export interface Last30DaysGraph {
  graph: GraphResponse;
  communities: { id: number; label: string; count: number }[];
  generatedAt: string | null;
}

export function loadLast30DaysGraph(): Last30DaysGraph {
  const raw = JSON.parse(fs.readFileSync(GRAPH_PATH, "utf-8")) as {
    nodes: GraphifyNode[];
    links: GraphifyLink[];
  };
  let labels: Record<string, string> = {};
  try {
    labels = JSON.parse(fs.readFileSync(LABELS_PATH, "utf-8")) as Record<string, string>;
  } catch {
    // labels are a nicety, not a requirement — fall back to "Community N"
  }

  const communityLabel = (c: number | undefined) =>
    c == null ? null : labels[String(c)] ?? `Community ${c}`;

  const nodes: GraphNode[] = raw.nodes.map((n) => ({
    id: n.id,
    label: n.label,
    // Anchors of the corpus — the three brief topics and the platforms every claim cites.
    // seed renders them larger with a 🔥, which is exactly the emphasis we want here.
    kind: "entity",
    category: communityLabel(n.community),
    entity_id: null, // nothing here is a tracked entity: keeps the ✨ explain panel off
    seed: n.id.startsWith("topic_"),
    entity_type: KIND_BY_FILE_TYPE[n.file_type ?? ""] ?? null,
    info: null,
  }));

  const edges: GraphEdge[] = raw.links.map((l) => ({
    source: l.source,
    target: l.target,
    relation: l.relation ?? "related_to",
    // EXTRACTED = stated outright in the source; INFERRED = the model's judgement; AMBIGUOUS =
    // flagged for review. Same three-tier honesty the main graph uses.
    kind:
      l.confidence === "EXTRACTED"
        ? "deterministic"
        : l.confidence === "AMBIGUOUS"
          ? "heuristic"
          : "reasoned",
    weight: l.confidence_score ?? l.weight ?? 1,
  }));

  const counts = new Map<number, number>();
  for (const n of raw.nodes) {
    if (n.community == null) continue;
    counts.set(n.community, (counts.get(n.community) ?? 0) + 1);
  }
  const communities = [...counts.entries()]
    .map(([id, count]) => ({ id, label: communityLabel(id)!, count }))
    .sort((a, b) => b.count - a.count);

  let generatedAt: string | null = null;
  try {
    generatedAt = fs.statSync(GRAPH_PATH).mtime.toISOString().slice(0, 10);
  } catch {
    // stat failing is not worth failing the page over
  }

  return { graph: { nodes, edges }, communities, generatedAt };
}
