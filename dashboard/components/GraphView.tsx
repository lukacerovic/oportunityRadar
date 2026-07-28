"use client";

import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import Graph from "graphology";
import forceAtlas2 from "graphology-layout-forceatlas2";
import { SigmaContainer, useLoadGraph, useSigma, useRegisterEvents } from "@react-sigma/core";
import { drawDiscNodeHover } from "sigma/rendering";
import type { Settings } from "sigma/settings";
import "@react-sigma/core/lib/style.css";
import type { GraphEdge, GraphNode, GraphResponse } from "@/lib/types";
import { titleize } from "@/lib/format";

// Deterministic category -> colour, so the same category always reads the same colour without a
// hand-maintained palette for ~29 slugs (see identity/vocab.py's category_slugs()).
function categoryColor(category: string | null): string {
  if (!category) return "#64748B";
  let hash = 0;
  for (let i = 0; i < category.length; i++) hash = (hash * 31 + category.charCodeAt(i)) >>> 0;
  return `hsl(${hash % 360}, 65%, 60%)`;
}

const DETERMINISTIC_COLOR = "#2DD4BF"; // project links: authorship / citations / dependencies / models
const REASONED_COLOR = "#A78BFA"; // matches the council-review purple — both are "a model's judgement"
// Team layer (Wikidata enrichment): people and orgs carry no category, so they get fixed colors
// that read apart from the category-hashed project/paper/model nodes.
const PERSON_COLOR = "#F59E0B";
const ORG_COLOR = "#38BDF8";
const WORK_COLOR = "#FB7185"; // notable-work entities (ChatGPT, TensorFlow, …)

// Relationship families get their own edge colors so employment, education, and ownership read
// apart at a glance. Anything not listed (built_by/cited/depends_on/authored_by/developed_by)
// stays teal — the project-provenance spine.
const EMPLOYMENT_COLOR = "#FB923C";
const EDUCATION_COLOR = "#A3E635";
const OWNERSHIP_COLOR = "#E879F9";
const EDGE_FAMILY: Record<string, string> = {
  employed_by: EMPLOYMENT_COLOR,
  formerly_at: EMPLOYMENT_COLOR,
  founded: EMPLOYMENT_COLOR,
  educated_at: EDUCATION_COLOR,
  advised_by: EDUCATION_COLOR,
  notable_work: WORK_COLOR,
  owned_by: OWNERSHIP_COLOR,
  subsidiary_of: OWNERSHIP_COLOR,
  invested_in: OWNERSHIP_COLOR,
};

function edgeColor(kind: GraphEdge["kind"], relations: string[]): string {
  if (kind === "reasoned") return REASONED_COLOR;
  for (const r of relations) {
    const family = EDGE_FAMILY[r];
    if (family) return family;
  }
  return DETERMINISTIC_COLOR;
}

function nodeColor(n: GraphNode): string {
  if (n.kind === "concept") return "#475569";
  if (n.entity_type === "person") return PERSON_COLOR;
  if (n.entity_type === "org") return ORG_COLOR;
  if (n.entity_type === "work") return WORK_COLOR;
  return categoryColor(n.category);
}

function buildGraph(data: GraphResponse): Graph {
  const graph = new Graph({ multi: true });
  const degree: Record<string, number> = {};
  for (const e of data.edges) {
    degree[e.source] = (degree[e.source] ?? 0) + 1;
    degree[e.target] = (degree[e.target] ?? 0) + 1;
  }

  for (const n of data.nodes) {
    const d = degree[n.id] ?? 1;
    const base = Math.min(4 + d * 1.5, 20);
    graph.addNode(n.id, {
      label: n.seed ? `🔥 ${n.label}` : n.label,
      size: n.seed ? Math.min(base + 4, 24) : base,
      color: nodeColor(n),
      x: Math.random(),
      y: Math.random(),
      nodeKind: n.kind,
      category: n.category,
      entityId: n.entity_id,
      seed: n.seed,
    });
  }
  // Merge parallel edges (e.g. Mira Murati is BOTH founder of and employed by Thinking
  // Machines Lab) into one line with the relations joined — sigma's container graph is not a
  // multigraph, and overlapping straight parallel edges would be indistinguishable anyway.
  const mergedEdges = new Map<
    string,
    { source: string; target: string; kind: GraphEdge["kind"]; relations: string[]; weight: number }
  >();
  for (const e of data.edges) {
    if (!graph.hasNode(e.source) || !graph.hasNode(e.target)) continue;
    const key = `${e.source}->${e.target}`;
    const existing = mergedEdges.get(key);
    if (existing) {
      if (!existing.relations.includes(e.relation)) existing.relations.push(e.relation);
      if (e.kind === "deterministic") existing.kind = "deterministic"; // provable wins the color
      existing.weight = Math.max(existing.weight, e.weight);
    } else {
      mergedEdges.set(key, {
        source: e.source,
        target: e.target,
        kind: e.kind,
        relations: [e.relation],
        weight: e.weight,
      });
    }
  }
  for (const e of mergedEdges.values()) {
    graph.addEdge(e.source, e.target, {
      size: e.kind === "deterministic" ? 1.2 : Math.max(0.6, e.weight),
      color: edgeColor(e.kind, e.relations),
      edgeKind: e.kind,
      relation: e.relations.join(" + "),
    });
  }

  // Layout cost scales hard with node count and runs synchronously on the main thread — at
  // ~2.4k nodes (teams landed on every trending repo) 150 un-optimized iterations froze the
  // tab. Barnes-Hut approximation + fewer iterations keeps big graphs under ~a second; small
  // graphs keep the prettier exact layout.
  const big = graph.order > 500;
  forceAtlas2.assign(graph, {
    iterations: big ? 50 : 150,
    settings: { ...forceAtlas2.inferSettings(graph), barnesHutOptimize: big },
  });
  return graph;
}

function LoadGraph({ data }: { data: GraphResponse }) {
  const loadGraph = useLoadGraph();
  useEffect(() => {
    loadGraph(buildGraph(data));
  }, [data, loadGraph]);
  return null;
}

function GraphEvents({ onSelect }: { onSelect: (nodeId: string | null) => void }) {
  const registerEvents = useRegisterEvents();
  const sigma = useSigma();
  useEffect(() => {
    registerEvents({
      clickNode: ({ node }) => onSelect(node),
      clickStage: () => onSelect(null),
      enterNode: () => {
        sigma.getContainer().style.cursor = "pointer";
      },
      leaveNode: () => {
        sigma.getContainer().style.cursor = "default";
      },
    });
    if (process.env.NODE_ENV !== "production") {
      (window as unknown as { __sigmaDebug?: unknown }).__sigmaDebug = sigma;
    }
  }, [registerEvents, sigma, onSelect]);
  return null;
}

function NodePanel({ node, onClose }: { node: (GraphNode & { neighbors: string[] }) | null; onClose: () => void }) {
  const router = useRouter();
  if (!node) return null;
  return (
    <div className="absolute right-4 top-4 w-72 rounded-lg border border-border bg-surface/95 p-4 shadow-lg backdrop-blur">
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0">
          <div className="truncate text-sm font-semibold text-text">{node.label}</div>
          <div className="mt-0.5 text-xs text-muted">
            {node.kind === "concept"
              ? "Concept (not a tracked entity)"
              : node.entity_type === "person"
                ? "Person"
                : node.entity_type === "org"
                  ? "Organization"
                  : node.entity_type === "work"
                    ? "Notable work"
                    : titleize(node.category)}
          </div>
          {node.seed && (
            <div className="mt-1 inline-block rounded-full bg-[#A78BFA14] px-2 py-0.5 text-[10px] font-medium text-[#A78BFA]">
              🔥 Trending — gated or breakout/accelerating
            </div>
          )}
        </div>
        <button onClick={onClose} className="text-faint hover:text-text" aria-label="Close">
          ✕
        </button>
      </div>
      {node.info?.description && (
        <p className="mt-2 text-xs text-muted">{node.info.description}</p>
      )}
      {node.info && (
        <dl className="mt-2 space-y-0.5 text-[11px]">
          {(
            [
              ["Positions", node.info.positions?.join(" · ")],
              ["Occupation", node.info.occupation?.join(", ")],
              ["Industry", node.info.industry?.join(", ")],
              ["HQ", node.info.headquarters?.join(", ")],
              ["Founded", node.info.inception],
              ["Dissolved", node.info.dissolved],
              ["Employees", node.info.employees],
              ["Awards", node.info.awards?.join(", ")],
            ] as const
          )
            .filter(([, v]) => v)
            .map(([k, v]) => (
              <div key={k} className="flex gap-2">
                <dt className="shrink-0 text-faint">{k}</dt>
                <dd className="text-muted">{v}</dd>
              </div>
            ))}
          {node.info.website && (
            <div className="flex gap-2">
              <dt className="shrink-0 text-faint">Web</dt>
              <dd className="truncate">
                <a
                  href={node.info.website}
                  target="_blank"
                  rel="noreferrer"
                  className="text-accent hover:underline"
                >
                  {node.info.website.replace(/^https?:\/\//, "")}
                </a>
              </dd>
            </div>
          )}
        </dl>
      )}
      <div className="mt-2 text-xs text-faint">{node.neighbors.length} connection(s)</div>
      {node.entity_id != null && (
        <button
          onClick={() => router.push(`/entity/${node.entity_id}`)}
          className="mt-3 w-full rounded-md border border-accent-dim px-3 py-1.5 text-xs text-accent hover:bg-card-hover"
        >
          Open entity →
        </button>
      )}
    </div>
  );
}

export function GraphView({ data }: { data: GraphResponse }) {
  const [selectedId, setSelectedId] = useState<string | null>(null);

  const nodeIndex = useMemo(() => new Map(data.nodes.map((n) => [n.id, n])), [data.nodes]);
  const neighborIndex = useMemo(() => {
    const idx = new Map<string, Set<string>>();
    for (const e of data.edges) {
      if (!idx.has(e.source)) idx.set(e.source, new Set());
      if (!idx.has(e.target)) idx.set(e.target, new Set());
      idx.get(e.source)!.add(e.target);
      idx.get(e.target)!.add(e.source);
    }
    return idx;
  }, [data.edges]);

  const selected = selectedId
    ? { ...nodeIndex.get(selectedId)!, neighbors: [...(neighborIndex.get(selectedId) ?? [])] }
    : null;

  return (
    <div>
      <div className="relative h-[calc(100vh-11rem)] overflow-hidden rounded-xl border border-border bg-surface">
        <SigmaContainer
          style={{ height: "100%", width: "100%", background: "transparent" }}
          settings={{
            renderLabels: true,
            labelColor: { color: "#E2E8F0" },
            labelSize: 11,
            // Labels only for nodes that render reasonably large (hubs); leaf contributors get
            // theirs on zoom-in. Cuts label draw cost ~10x on team-heavy views.
            labelRenderedSizeThreshold: 7,
            hideEdgesOnMove: true,
            // The hover bubble is white, so the light canvas label color is unreadable there —
            // re-draw hover labels in dark slate.
            defaultDrawNodeHover: (ctx, data, settings) =>
              drawDiscNodeHover(ctx, data, {
                ...settings,
                labelColor: { color: "#0F172A" },
              } as Settings),
            defaultNodeColor: "#64748B",
            defaultEdgeColor: "#334155",
          }}
        >
          <LoadGraph data={data} />
          <GraphEvents onSelect={setSelectedId} />
        </SigmaContainer>

        <NodePanel node={selected} onClose={() => setSelectedId(null)} />
      </div>

      <div className="mt-2 flex flex-wrap items-center gap-x-5 gap-y-1.5 px-1 text-[11px]">
        {(
          [
            [DETERMINISTIC_COLOR, "Project links (authored / built / cited / depends / developed)"],
            [EMPLOYMENT_COLOR, "Employment & founders"],
            [EDUCATION_COLOR, "Education & advisors"],
            [WORK_COLOR, "Notable work"],
            [OWNERSHIP_COLOR, "Ownership & investors"],
            [REASONED_COLOR, "LLM-reasoned similarity"],
          ] as const
        ).map(([color, label]) => (
          <div key={label} className="flex items-center gap-2">
            <span className="h-[2px] w-4" style={{ background: color }} />
            <span className="text-muted">{label}</span>
          </div>
        ))}
        <div className="flex items-center gap-2">
          <span className="h-2.5 w-2.5 rounded-full" style={{ background: PERSON_COLOR }} />
          <span className="text-muted">Person</span>
          <span className="ml-2 h-2.5 w-2.5 rounded-full" style={{ background: ORG_COLOR }} />
          <span className="text-muted">Organization</span>
          <span className="ml-2 h-2.5 w-2.5 rounded-full" style={{ background: WORK_COLOR }} />
          <span className="text-muted">Work</span>
        </div>
        <div className="flex items-center gap-2">
          <span>🔥</span>
          <span className="text-muted">Trending — gated or breakout/accelerating</span>
        </div>
      </div>
    </div>
  );
}
