import { compactNum, shortDate } from "@/lib/format";
import type { EvidenceItem } from "@/lib/types";

// Where the entity was found and what those sources say — the "go read it yourself" section.
export function EvidenceList({ items }: { items: EvidenceItem[] }) {
  if (items.length === 0) {
    return (
      <div className="panel p-6 text-sm text-muted">
        No readable sources captured yet. Run <code className="text-accent">enrich-launches</code> /{" "}
        <code className="text-accent">enrich-readmes</code> to fetch the linked content.
      </div>
    );
  }
  return (
    <div className="space-y-2.5">
      {items.map((it, i) => (
        <div key={i} className="panel p-4">
          <div className="flex items-start justify-between gap-3">
            <div className="min-w-0">
              <div className="flex items-center gap-2">
                <span className="rounded-full border border-border px-2 py-0.5 text-[10px] uppercase tracking-wide text-muted">
                  {it.kind}
                </span>
                {it.score != null && (
                  <span className="text-[11px] text-faint">{compactNum(it.score)} pts/dl</span>
                )}
                <span className="text-[11px] text-faint">{shortDate(it.occurred_at)}</span>
              </div>
              {it.title && (
                <div className="mt-1.5 truncate text-sm font-medium text-text">{it.title}</div>
              )}
            </div>
            {it.url && (
              <a
                href={it.url}
                target="_blank"
                rel="noopener noreferrer"
                className="shrink-0 inline-flex items-center gap-1 rounded-lg border border-border px-2.5 py-1 text-xs text-accent hover:bg-card-hover"
              >
                Open
                <svg width="12" height="12" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2" strokeLinecap="round" strokeLinejoin="round">
                  <path d="M18 13v6a2 2 0 01-2 2H5a2 2 0 01-2-2V8a2 2 0 012-2h6" />
                  <path d="M15 3h6v6M10 14L21 3" />
                </svg>
              </a>
            )}
          </div>
          {it.text && (
            <p className="mt-2.5 whitespace-pre-line text-[13px] leading-relaxed text-muted line-clamp-6">
              {it.text}
            </p>
          )}
        </div>
      ))}
    </div>
  );
}
