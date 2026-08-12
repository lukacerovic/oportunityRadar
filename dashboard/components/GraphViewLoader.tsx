"use client";

import dynamic from "next/dynamic";
import type { GraphResponse } from "@/lib/types";

// sigma.js touches WebGL2RenderingContext at module-load time, which doesn't exist under Next's
// server-side render — ssr:false forces it to load only in the browser. next/dynamic with
// ssr:false is only legal inside a Client Component, hence this thin wrapper around the real
// GraphView (which itself has no reason to be client-only beyond sigma's own requirement).
const GraphView = dynamic(() => import("./GraphView").then((m) => m.GraphView), {
  ssr: false,
  loading: () => (
    <div className="flex h-[calc(100vh-8rem)] items-center justify-center rounded-xl border border-border bg-surface text-sm text-muted">
      Loading graph…
    </div>
  ),
});

export function GraphViewLoader({
  data,
  explainEntityId = null,
  focusEntityIds = [],
}: {
  data: GraphResponse;
  explainEntityId?: number | null;
  focusEntityIds?: number[];
}) {
  return (
    <GraphView data={data} explainEntityId={explainEntityId} focusEntityIds={focusEntityIds} />
  );
}
