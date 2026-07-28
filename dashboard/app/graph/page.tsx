import Link from "next/link";
import { getGraph } from "@/lib/api";
import { TopNav } from "@/components/TopNav";
import { ApiError } from "@/components/ApiError";
import { GraphViewLoader } from "@/components/GraphViewLoader";
import { InfoButton } from "@/components/InfoModal";
import { HELP } from "@/lib/help";
import type { GraphResponse } from "@/lib/types";

export const dynamic = "force-dynamic";

export default async function GraphPage({
  searchParams,
}: {
  searchParams: { trending?: string; q?: string };
}) {
  // Trending is the DEFAULT: the full graph is ~12k nodes (9k+ of them paper authors since the
  // Wikidata team enrichment) and the force layout can't render that pleasantly. Full view is
  // opt-in via ?trending=false. A search (q) overrides both — the API returns the two-hop
  // neighborhood around name matches, so "thinking machines" shows the model, its org, and the
  // org's founders without loading the rest of the universe.
  const q = (searchParams.q ?? "").trim();
  const trending = searchParams.trending !== "false";
  let data: GraphResponse;
  try {
    data = await getGraph(q ? { q } : { trending });
  } catch (e) {
    return (
      <>
        <TopNav active="/graph" />
        <ApiError error={e} />
      </>
    );
  }

  // Search view: auto-open the ✨ explanation panel for the best match — prefer the tracked
  // artifact/org the user searched for over person nodes pulled in as neighbors.
  let explainTarget: number | null = null;
  if (q) {
    const ql = q.toLowerCase();
    const matches = data.nodes.filter(
      (n) => n.entity_id != null && n.label.toLowerCase().includes(ql)
    );
    const preferred = matches.find((n) => n.entity_type !== "person") ?? matches[0];
    explainTarget = preferred?.entity_id ?? null;
  }

  return (
    <>
      <TopNav active="/graph" />
      <main className="mx-auto max-w-[1400px] px-5 py-6">
        <div className="mb-4 flex flex-wrap items-end justify-between gap-4">
          <div>
            <div className="flex items-center gap-2">
              <h1 className="text-xl font-semibold tracking-tight">Graph</h1>
              <InfoButton content={HELP.graph} />
            </div>
            <p className="mt-1 text-sm text-muted">
              {data.nodes.length} nodes · {data.edges.length} edges — click a node for details,
              drag to pan, scroll to zoom.
            </p>
          </div>
          <div className="flex items-center gap-3">
            <form action="/graph" className="flex items-center gap-2">
              <input
                type="search"
                name="q"
                defaultValue={q}
                placeholder="Search ALL entities… (e.g. thinking machines)"
                className="w-64 rounded-full border border-border bg-surface px-3 py-1 text-xs text-text placeholder:text-faint focus:border-accent-dim focus:outline-none"
              />
              {q && (
                <Link href="/graph" className="text-xs text-muted hover:text-text">
                  ✕ clear
                </Link>
              )}
            </form>
            <Link
              href={trending && !q ? "/graph?trending=false" : "/graph"}
              title="Only entities that passed the significance gate or are breakout/accelerating, plus their direct neighbors — cuts long-tail clutter like citation-only paper stubs. On by default."
              className={`rounded-full border px-3 py-1 text-xs transition ${
                trending && !q ? "text-bg" : "text-muted hover:text-text"
              }`}
              style={
                trending && !q
                  ? { background: "#A78BFA", borderColor: "#A78BFA" }
                  : { borderColor: "#1E2A2C" }
              }
            >
              {trending && !q ? "🔥 Trending only" : "Show all"}
            </Link>
          </div>
        </div>

        {data.nodes.length === 0 ? (
          <div className="panel p-10 text-center text-sm text-muted">
            {q ? (
              <>
                No tracked entity matches <span className="text-text">&ldquo;{q}&rdquo;</span>.{" "}
                <Link href="/graph" className="text-accent hover:underline">
                  Back to trending →
                </Link>
              </>
            ) : trending ? (
              <>
                No entity has passed the gate or is breakout/accelerating yet — nothing to show in
                trending mode.{" "}
                <Link href="/graph?trending=false" className="text-accent hover:underline">
                  View the full graph →
                </Link>
              </>
            ) : (
              <>
                No graph data yet. Run <code className="text-accent">seismo derive-edges</code> for
                the deterministic spine, or import a graphify pass&rsquo;s reasoned edges via{" "}
                <code className="text-accent">scripts/import_semantic_edges.py</code>.
              </>
            )}
          </div>
        ) : (
          <GraphViewLoader data={data} explainEntityId={explainTarget} />
        )}
      </main>
    </>
  );
}
