import Link from "next/link";
import { getBriefs } from "@/lib/api";
import { titleize } from "@/lib/format";
import type { BriefListItem } from "@/lib/types";
import { TopNav } from "@/components/TopNav";
import { ApiError } from "@/components/ApiError";
import { InfoButton } from "@/components/InfoModal";
import { HELP } from "@/lib/help";

export const dynamic = "force-dynamic";

// Brief status → how the inbox labels + colours it (doc 08 §4 review workflow).
const STATUS: Record<string, { label: string; color: string }> = {
  draft: { label: "Draft — needs review", color: "#38BDF8" },
  published: { label: "Published", color: "#34D399" },
  rejected: { label: "Rejected", color: "#F59E0B" },
  failed: { label: "Failed validation", color: "#F87171" },
  pending: { label: "Pending (budget)", color: "#64748B" },
};

export default async function BriefInbox() {
  let items: BriefListItem[];
  try {
    items = await getBriefs();
  } catch (e) {
    return (
      <>
        <TopNav active="/brief" />
        <ApiError error={e} />
      </>
    );
  }

  return (
    <>
      <TopNav active="/brief" />
      <main className="mx-auto max-w-[1000px] px-5 py-6">
        <div className="mb-5">
          <div className="flex items-center gap-2">
            <h1 className="text-xl font-semibold tracking-tight">Impact Briefs</h1>
            <InfoButton content={HELP.briefList} />
          </div>
          <p className="mt-1 text-sm text-muted">
            Who is exposed to each rising entity, how, and what to watch. Every brief is drafted by
            the checkpoint and <span className="text-accent">reviewed by a human</span> before it
            publishes (doc 08). We explain exposure — never prices.
          </p>
        </div>

        {items.length === 0 && (
          <div className="panel p-10 text-center text-sm text-muted">
            No briefs yet. The gate feeds this queue: once an entity passes, run{" "}
            <code className="text-accent">seismo brief --week &lt;week&gt;</code> (or{" "}
            <code className="text-accent">--entity-id N</code>) to draft one.
          </div>
        )}

        <div className="space-y-2">
          {items.map((b) => {
            const s = STATUS[b.status] ?? { label: b.status, color: "#64748B" };
            return (
              <Link
                key={b.id}
                href={`/brief/${b.entity_id}`}
                className="panel flex flex-wrap items-center gap-x-5 gap-y-2 p-4 transition hover:bg-card-hover"
              >
                <div className="min-w-[200px] flex-1">
                  <div className="flex items-center gap-2">
                    <span className="truncate text-[15px] font-semibold">{b.entity_name}</span>
                    <span className="tabular text-[10px] text-faint">v{b.version}</span>
                    <span
                      className="shrink-0 rounded-full px-2 py-0.5 text-[10px] font-medium"
                      style={{ color: s.color, background: `${s.color}14`, border: `1px solid ${s.color}33` }}
                    >
                      {s.label}
                    </span>
                  </div>
                  {b.summary && (
                    <div className="mt-1 line-clamp-1 text-xs text-muted">{b.summary}</div>
                  )}
                </div>
                <div className="flex flex-wrap gap-1.5">
                  {b.mechanisms.map((mech) => (
                    <span
                      key={mech}
                      className="rounded-md border border-border bg-surface px-2 py-0.5 text-[10px] text-muted"
                    >
                      {titleize(mech)}
                    </span>
                  ))}
                </div>
                <div className="w-[70px] text-right">
                  <div className="tabular text-sm text-text">{b.n_exposures}</div>
                  <div className="text-[10px] uppercase tracking-wide text-faint">exposures</div>
                </div>
              </Link>
            );
          })}
        </div>
      </main>
    </>
  );
}
