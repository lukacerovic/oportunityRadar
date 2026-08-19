import Link from "next/link";
import { TopNav } from "@/components/TopNav";
import { GraphViewLoader } from "@/components/GraphViewLoader";
import { loadLast30DaysGraph } from "@/lib/last30days";

export const dynamic = "force-dynamic";

const BRIEFS = [
  { topic: "Guardrails / prompt injection / MCP security", runtime: "185s" },
  { topic: "LLM gateway / routing / failover", runtime: "146s" },
  { topic: "Agent long-term memory / persistent context", runtime: "168s" },
];

export default function ResearchPage() {
  let data;
  try {
    data = loadLast30DaysGraph();
  } catch {
    return (
      <>
        <TopNav active="/research" />
        <main className="mx-auto max-w-[1400px] px-5 py-6">
          <div className="panel p-10 text-center text-sm text-muted">
            No last30days graph built yet. See{" "}
            <code className="text-accent">LAST30DAYS_RUNBOOK.md</code> — run a few briefs into{" "}
            <code className="text-accent">research/last30days/</code>, then{" "}
            <code className="text-accent">graphify export html</code> from that folder.
          </div>
        </main>
      </>
    );
  }

  const { graph, communities, generatedAt } = data;

  return (
    <>
      <TopNav active="/research" />
      <main className="mx-auto max-w-[1400px] px-5 py-6">
        <div className="mb-4 flex flex-wrap items-end justify-between gap-4">
          <div>
            <h1 className="text-xl font-semibold tracking-tight">
              Community research{" "}
              <span className="ml-1 rounded-md border border-border px-1.5 py-0.5 align-middle text-[10px] uppercase tracking-wide text-muted">
                external · not collected
              </span>
            </h1>
            <p className="mt-1 max-w-3xl text-sm text-muted">
              {graph.nodes.length} nodes · {graph.edges.length} edges from{" "}
              {BRIEFS.length} manually-run last30days briefs
              {generatedAt ? ` (${generatedAt})` : ""}. This is the{" "}
              <span className="text-text">demand side</span> — what practitioners are saying on
              Reddit, HN, TikTok, YouTube, GitHub and Digg. It never enters Postgres: social and
              video content has no reliable <code>occurred_at</code>, so it would break invariants
              1 and 2.
            </p>
          </div>
          <Link
            href="/graph"
            className="rounded-full border border-border px-3 py-1 text-xs text-muted transition hover:text-text"
          >
            ← Collected graph
          </Link>
        </div>

        <div className="mb-4 grid gap-2 sm:grid-cols-3">
          {BRIEFS.map((b) => (
            <div key={b.topic} className="panel px-3 py-2">
              <div className="text-xs text-text">{b.topic}</div>
              <div className="mt-0.5 text-[11px] text-faint">brief · {b.runtime}</div>
            </div>
          ))}
        </div>

        <div className="mb-4 flex flex-wrap gap-1.5">
          {communities.map((c) => (
            <span
              key={c.id}
              className="rounded-full border border-border px-2.5 py-1 text-[11px] text-muted"
            >
              {c.label} <span className="text-faint">{c.count}</span>
            </span>
          ))}
        </div>

        <GraphViewLoader data={graph} explainEntityId={null} focusEntityIds={[]} />
      </main>
    </>
  );
}
