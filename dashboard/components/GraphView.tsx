"use client";

import { useEffect, useMemo, useState } from "react";
import { useRouter } from "next/navigation";
import Graph from "graphology";
import forceAtlas2 from "graphology-layout-forceatlas2";
import {
  SigmaContainer,
  useLoadGraph,
  useSigma,
  useRegisterEvents,
  useSetSettings,
  useCamera,
} from "@react-sigma/core";
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

const DETERMINISTIC_COLOR = "#2DD4BF"; // matches the accent used for the deterministic spine elsewhere
const REASONED_COLOR = "#A78BFA"; // matches the council-review purple — both are "a model's judgement"

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
      color: n.kind === "concept" ? "#475569" : categoryColor(n.category),
      x: Math.random(),
      y: Math.random(),
      nodeKind: n.kind,
      category: n.category,
      entityId: n.entity_id,
      seed: n.seed,
    });
  }
  for (const e of data.edges) {
    if (!graph.hasNode(e.source) || !graph.hasNode(e.target)) continue;
    graph.addEdge(e.source, e.target, {
      size: e.kind === "deterministic" ? 1.2 : Math.max(0.6, e.weight),
      color: e.kind === "deterministic" ? DETERMINISTIC_COLOR : REASONED_COLOR,
      edgeKind: e.kind,
      relation: e.relation,
    });
  }

  forceAtlas2.assign(graph, {
    iterations: 150,
    settings: forceAtlas2.inferSettings(graph),
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

// Registers sigma node/edge reducers so search filters the render without touching the
// underlying graphology instance — clearing the query restores the identity reducers.
function SearchController({
  keepIds,
  matchIds,
  focusId,
}: {
  keepIds: Set<string> | null;
  matchIds: Set<string>;
  focusId: string | null;
}) {
  const sigma = useSigma();
  const setSettings = useSetSettings();
  const { gotoNode } = useCamera({ duration: 400 });

  useEffect(() => {
    if (!keepIds) {
      setSettings({
        nodeReducer: (_node, data) => data,
        edgeReducer: (_edge, data) => data,
      });
      return;
    }
    const graph = sigma.getGraph();
    setSettings({
      nodeReducer: (node, data) => {
        if (matchIds.has(node)) return { ...data, highlighted: true, zIndex: 1 };
        if (keepIds.has(node)) return data;
        return { ...data, hidden: true, label: "" };
      },
      edgeReducer: (edge, data) => {
        const [source, target] = graph.extremities(edge);
        return keepIds.has(source) && keepIds.has(target) ? data : { ...data, hidden: true };
      },
    });
  }, [keepIds, matchIds, sigma, setSettings]);

  useEffect(() => {
    if (focusId) gotoNode(focusId);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [focusId]);

  return null;
}

function GraphSearchBox({
  nodes,
  onSelect,
  query,
  setQuery,
  matchCount,
}: {
  nodes: GraphNode[];
  onSelect: (id: string) => void;
  query: string;
  setQuery: (q: string) => void;
  matchCount: number | null;
}) {
  const [focused, setFocused] = useState(false);
  const q = query.trim().toLowerCase();
  const suggestions = q
    ? nodes.filter((n) => n.label.toLowerCase().includes(q)).slice(0, 8)
    : [];

  return (
    <div className="absolute left-4 top-4 w-72">
      <div className="relative">
        <input
          type="text"
          value={query}
          onChange={(e) => setQuery(e.target.value)}
          onFocus={() => setFocused(true)}
          onBlur={() => setFocused(false)}
          placeholder="Search entities…"
          className="w-full rounded-lg border border-border bg-surface/95 px-3 py-2 text-sm text-text placeholder:text-faint backdrop-blur focus:outline-none focus:ring-1 focus:ring-accent"
        />
        {query && (
          <button
            onClick={() => setQuery("")}
            aria-label="Clear search"
            className="absolute right-2 top-1/2 -translate-y-1/2 text-faint hover:text-text"
          >
            ✕
          </button>
        )}
      </div>

      {query && (
        <div className="mt-1 text-[11px] text-muted">
          {matchCount === null
            ? null
            : matchCount === 0
              ? "No matches"
              : `Showing ${matchCount} node${matchCount === 1 ? "" : "s"} (matches + direct connections)`}
        </div>
      )}

      {focused && suggestions.length > 0 && (
        <div className="mt-1 max-h-72 overflow-y-auto rounded-lg border border-border bg-surface/95 shadow-lg backdrop-blur">
          {suggestions.map((n) => (
            <button
              key={n.id}
              onMouseDown={(e) => {
                e.preventDefault();
                setQuery(n.label);
                onSelect(n.id);
              }}
              className="block w-full truncate px-3 py-1.5 text-left text-xs text-text hover:bg-card-hover"
            >
              {n.label}
              {n.category && <span className="ml-1.5 text-faint">· {titleize(n.category)}</span>}
            </button>
          ))}
        </div>
      )}
    </div>
  );
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
            {node.kind === "concept" ? "Concept (not a tracked entity)" : titleize(node.category)}
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
  const [query, setQuery] = useState("");
  const [focusId, setFocusId] = useState<string | null>(null);

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

  const { matchIds, keepIds } = useMemo(() => {
    const q = query.trim().toLowerCase();
    if (!q) return { matchIds: new Set<string>(), keepIds: null as Set<string> | null };
    const matchIds = new Set<string>();
    for (const n of data.nodes) if (n.label.toLowerCase().includes(q)) matchIds.add(n.id);
    const keepIds = new Set<string>(matchIds);
    for (const id of matchIds) for (const nb of neighborIndex.get(id) ?? []) keepIds.add(nb);
    return { matchIds, keepIds };
  }, [query, data.nodes, neighborIndex]);

  const handleSelect = (id: string) => {
    setSelectedId(id);
    setFocusId(id);
  };

  return (
    <div className="relative h-[calc(100vh-8rem)] overflow-hidden rounded-xl border border-border bg-surface">
      <SigmaContainer
        style={{ height: "100%", width: "100%", background: "transparent" }}
        settings={{
          renderLabels: true,
          labelColor: { color: "#E2E8F0" },
          labelSize: 11,
          defaultNodeColor: "#64748B",
          defaultEdgeColor: "#334155",
        }}
      >
        <LoadGraph data={data} />
        <GraphEvents onSelect={setSelectedId} />
        <SearchController keepIds={keepIds} matchIds={matchIds} focusId={focusId} />
      </SigmaContainer>

      <GraphSearchBox
        nodes={data.nodes}
        onSelect={handleSelect}
        query={query}
        setQuery={setQuery}
        matchCount={keepIds ? keepIds.size : null}
      />

      <div className="pointer-events-none absolute bottom-4 left-4 flex flex-col gap-1.5 rounded-lg border border-border bg-surface/90 p-3 text-[11px] backdrop-blur">
        <div className="flex items-center gap-2">
          <span className="h-[2px] w-4" style={{ background: DETERMINISTIC_COLOR }} />
          <span className="text-muted">Deterministic (built_by / cited / depends_on)</span>
        </div>
        <div className="flex items-center gap-2">
          <span className="h-[2px] w-4" style={{ background: REASONED_COLOR }} />
          <span className="text-muted">LLM-reasoned (semantically_similar_to / conceptually_related_to)</span>
        </div>
        <div className="flex items-center gap-2">
          <span>🔥</span>
          <span className="text-muted">Trending — gated or breakout/accelerating</span>
        </div>
      </div>

      <NodePanel node={selected} onClose={() => setSelectedId(null)} />
    </div>
  );
}
