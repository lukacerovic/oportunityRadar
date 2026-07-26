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
  searchParams: { trending?: string };
}) {
  const trending = searchParams.trending === "true";
  let data: GraphResponse;
  try {
    data = await getGraph({ trending });
  } catch (e) {
    return (
      <>
        <TopNav active="/graph" />
        <ApiError error={e} />
      </>
    );
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
          <Link
            href={trending ? "/graph" : "/graph?trending=true"}
            title="Only entities that passed the significance gate or are breakout/accelerating, plus their direct neighbors — cuts long-tail clutter like citation-only paper stubs."
            className={`rounded-full border px-3 py-1 text-xs transition ${
              trending ? "text-bg" : "text-muted hover:text-text"
            }`}
            style={trending ? { background: "#A78BFA", borderColor: "#A78BFA" } : { borderColor: "#1E2A2C" }}
          >
            🔥 Trending only
          </Link>
        </div>

        {data.nodes.length === 0 ? (
          <div className="panel p-10 text-center text-sm text-muted">
            {trending ? (
              <>
                No entity has passed the gate or is breakout/accelerating yet — nothing to show in
                trending mode. <Link href="/graph" className="text-accent hover:underline">View the full graph →</Link>
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
          <GraphViewLoader data={data} />
        )}
      </main>
    </>
  );
}
