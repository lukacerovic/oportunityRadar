"use client";

import { useEffect, useState } from "react";
import { API_BASE } from "@/lib/api";
import type { GraphExplanation } from "@/lib/types";

// Markdown-lite: the narration uses headings, bullets, **bold** and `code` — render those
// without pulling in a markdown dependency.
function inline(text: string): React.ReactNode[] {
  return text.split(/(\*\*[^*]+\*\*|`[^`]+`)/g).map((part, i) => {
    if (part.startsWith("**") && part.endsWith("**")) {
      return (
        <strong key={i} className="font-semibold text-text">
          {part.slice(2, -2)}
        </strong>
      );
    }
    if (part.startsWith("`") && part.endsWith("`")) {
      return (
        <code key={i} className="rounded bg-card-hover px-1 text-[11px] text-accent">
          {part.slice(1, -1)}
        </code>
      );
    }
    return part;
  });
}

function Markdown({ text }: { text: string }) {
  const blocks: React.ReactNode[] = [];
  let bullets: string[] = [];
  const flush = (key: number) => {
    if (!bullets.length) return;
    blocks.push(
      <ul key={`ul-${key}`} className="mb-2 list-disc space-y-1 pl-4">
        {bullets.map((b, i) => (
          <li key={i}>{inline(b)}</li>
        ))}
      </ul>
    );
    bullets = [];
  };
  text.split("\n").forEach((raw, i) => {
    const line = raw.trim();
    if (line.startsWith("- ") || line.startsWith("* ")) {
      bullets.push(line.slice(2));
      return;
    }
    flush(i);
    if (!line) return;
    const heading = line.match(/^#{1,4}\s+(.*)$/);
    if (heading) {
      blocks.push(
        <h4 key={i} className="mb-1 mt-3 text-[11px] font-semibold uppercase tracking-wide text-text first:mt-0">
          {inline(heading[1])}
        </h4>
      );
    } else {
      blocks.push(
        <p key={i} className="mb-2">
          {inline(line)}
        </p>
      );
    }
  });
  flush(-1);
  return <div className="text-xs leading-relaxed text-muted">{blocks}</div>;
}

type State =
  | { kind: "loading" }
  | { kind: "ready"; data: GraphExplanation }
  | { kind: "missing" } // no stored narration yet — offer on-demand generation
  | { kind: "generating" }
  | { kind: "empty" } // entity has no relationships to narrate
  | { kind: "error"; message: string };

// AI-narrated context for the entity's relationship subgraph. Stored rows load instantly;
// "Generate now" runs the LLM synchronously (claude_cli ≈ 20-60s) and persists the result, so
// the next visitor gets it for free.
export function ExplainPanel({ entityId, onClose }: { entityId: number; onClose: () => void }) {
  const [state, setState] = useState<State>({ kind: "loading" });

  useEffect(() => {
    let cancelled = false;
    setState({ kind: "loading" });
    fetch(`${API_BASE}/graph/explain?entity_id=${entityId}`)
      .then(async (res) => {
        if (cancelled) return;
        if (res.status === 404) return setState({ kind: "missing" });
        if (!res.ok) return setState({ kind: "error", message: `API ${res.status}` });
        setState({ kind: "ready", data: (await res.json()) as GraphExplanation });
      })
      .catch((e) => !cancelled && setState({ kind: "error", message: String(e) }));
    return () => {
      cancelled = true;
    };
  }, [entityId]);

  const generate = async () => {
    setState({ kind: "generating" });
    try {
      const res = await fetch(`${API_BASE}/graph/explain?entity_id=${entityId}`, {
        method: "POST",
      });
      if (res.status === 422) return setState({ kind: "empty" });
      if (!res.ok) return setState({ kind: "error", message: `API ${res.status}` });
      setState({ kind: "ready", data: (await res.json()) as GraphExplanation });
    } catch (e) {
      setState({ kind: "error", message: String(e) });
    }
  };

  return (
    <div className="absolute bottom-4 left-4 top-4 z-10 flex w-96 flex-col overflow-hidden rounded-lg border border-border bg-surface/95 shadow-lg backdrop-blur">
      <div className="flex items-start justify-between gap-2 border-b border-border p-4 pb-3">
        <div className="min-w-0">
          <div className="text-sm font-semibold text-text">✨ Graph explained</div>
          {state.kind === "ready" && (
            <div className="mt-0.5 truncate text-xs text-muted">
              {state.data.entity_name} · {state.data.node_count} entities ·{" "}
              {state.data.edge_count} relationships
            </div>
          )}
        </div>
        <button onClick={onClose} className="text-faint hover:text-text" aria-label="Close">
          ✕
        </button>
      </div>

      <div className="min-h-0 flex-1 overflow-y-auto p-4">
        {state.kind === "loading" && <p className="text-xs text-muted">Loading…</p>}

        {state.kind === "missing" && (
          <div className="space-y-3 text-xs text-muted">
            <p>No narration has been generated for this graph yet.</p>
            <button
              onClick={generate}
              className="rounded-md border border-accent-dim px-3 py-1.5 text-accent hover:bg-card-hover"
            >
              ✨ Generate now (~30–60s)
            </button>
          </div>
        )}

        {state.kind === "generating" && (
          <p className="animate-pulse text-xs text-muted">
            Reading the graph and writing the explanation… this takes ~30–60 seconds.
          </p>
        )}

        {state.kind === "empty" && (
          <p className="text-xs text-muted">
            This entity has no relationships in the graph yet — nothing to narrate. Team
            enrichment may still be pending for it.
          </p>
        )}

        {state.kind === "error" && (
          <p className="text-xs text-[#F87171]">Failed: {state.message}</p>
        )}

        {state.kind === "ready" && (
          <div className="space-y-4">
            {state.data.stale && (
              <p className="rounded-md border border-border bg-card-hover px-2 py-1 text-[11px] text-muted">
                ⟳ The graph gained new data since this was written — it will be rewritten in the
                next daily run.
              </p>
            )}
            {(
              [
                ["Overview", state.data.overview],
                ["Key people", state.data.key_people],
                ["Organizations", state.data.organizations],
                ["Industry context", state.data.industry_context],
                ["What this signals", state.data.signals],
              ] as const
            )
              .filter(([, body]) => body && !body.startsWith("(mock provider"))
              .map(([title, body]) => (
                <section key={title}>
                  <h3 className="mb-1 text-xs font-semibold uppercase tracking-wide text-faint">
                    {title}
                  </h3>
                  <Markdown text={body} />
                </section>
              ))}
            <p className="border-t border-border pt-2 text-[10px] text-faint">
              Generated by {state.data.model} ·{" "}
              {new Date(state.data.updated_at).toLocaleString()} · based only on relationships
              shown in this graph
            </p>
          </div>
        )}
      </div>
    </div>
  );
}
