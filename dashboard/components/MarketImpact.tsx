import Link from "next/link";
import { titleize } from "@/lib/format";
import type { Brief } from "@/lib/types";

// Surfaces the Brief (public-market thesis) directly on the entity card. Most entities have none
// yet — a Brief is only written once an item clears the weekly significance gate.
export function MarketImpact({ brief, entityId }: { brief: Brief | null; entityId: number }) {
  if (!brief) {
    return (
      <div className="panel p-6 text-sm text-muted">
        <div className="label mb-1">Market impact</div>
        No public-market analysis yet. A brief — which companies and revenue lines this could move —
        is written once an item clears the weekly significance gate (momentum × reach × novelty).
      </div>
    );
  }
  const dirSign = (d: string) =>
    /up|increase|tailwind|positive|benefit/i.test(d) ? "▲" : /down|decrease|headwind|negative|risk/i.test(d) ? "▼" : "•";
  return (
    <div className="panel p-4">
      <div className="mb-2 flex items-center justify-between">
        <div className="label">Market impact</div>
        <Link href={`/brief/${entityId}`} className="text-xs text-accent hover:underline">
          Full brief →
        </Link>
      </div>
      {brief.summary && <p className="text-[13px] leading-relaxed text-text">{brief.summary}</p>}

      {brief.exposures.length > 0 && (
        <div className="mt-3 space-y-1.5">
          <div className="label">Exposed companies / lines</div>
          {brief.exposures.map((e, i) => (
            <div key={i} className="flex items-center justify-between gap-3 text-[13px]">
              <span className="min-w-0 truncate text-text">
                {e.ref}
                {e.revenue_line ? <span className="text-muted"> · {e.revenue_line}</span> : null}
              </span>
              <span className="shrink-0 text-muted">
                {dirSign(e.direction)} {titleize(e.magnitude_class)}
              </span>
            </div>
          ))}
        </div>
      )}

      {brief.mechanisms.length > 0 && (
        <div className="mt-3">
          <div className="label mb-1">Why</div>
          <ul className="list-disc space-y-0.5 pl-4 text-[13px] text-muted">
            {brief.mechanisms.slice(0, 3).map((mstr, i) => (
              <li key={i}>{mstr}</li>
            ))}
          </ul>
        </div>
      )}
    </div>
  );
}
