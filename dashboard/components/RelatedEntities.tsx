import Link from "next/link";
import { titleize } from "@/lib/format";
import type { RelatedEntity } from "@/lib/types";

// Surfaces entity_semantic_edges neighbors — an LLM's judgement of what's related, never a rule's
// (see GRAPH_PLAN.md consumer #1). Concepts (entity_id null) render as plain text, not a link.
export function RelatedEntities({ items }: { items: RelatedEntity[] }) {
  if (items.length === 0) {
    return (
      <div className="panel p-4 text-sm text-muted">
        <div className="label mb-1">Related</div>
        No LLM-reasoned relations recorded for this entity yet.
      </div>
    );
  }
  const relationLabel = (r: string) =>
    r === "semantically_similar_to" ? "similar to" : r === "conceptually_related_to" ? "related to" : titleize(r);

  return (
    <div className="panel p-4">
      <div className="mb-2 flex items-center justify-between">
        <div className="label">Related</div>
        <Link href="/graph" className="text-xs text-accent hover:underline">
          View graph →
        </Link>
      </div>
      <div className="space-y-1.5">
        {items.slice(0, 12).map((r, i) => (
          <div key={i} className="flex items-center justify-between gap-3 text-[13px]">
            <span className="min-w-0 truncate text-text">
              {r.entity_id != null ? (
                <Link href={`/entity/${r.entity_id}`} className="hover:underline">
                  {r.label}
                </Link>
              ) : (
                <span className="text-muted">{r.label}</span>
              )}
              <span className="text-faint"> · {relationLabel(r.relation)}</span>
            </span>
            <span className="shrink-0 text-faint">{Math.round(r.confidence_score * 100)}%</span>
          </div>
        ))}
      </div>
    </div>
  );
}
