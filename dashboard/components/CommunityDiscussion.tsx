import { compactNum, shortDate } from "@/lib/format";
import type { CommunityResearch, CommunityThread } from "@/lib/types";

// What the community is saying about this entity, grouped by source (GitHub / Hugging Face /
// Hacker News). Each source is researched independently; a "found" source lists its most relevant
// discussion threads with the actual collected comments.
const SOURCE_LABEL: Record<string, string> = {
  github: "GitHub",
  hf: "Hugging Face",
  hn: "Hacker News",
};

export function CommunityDiscussion({ items }: { items: CommunityResearch[] }) {
  // The 'summary' row is the cross-source AI verdict — rendered separately in CommunityVerdict.
  const researched = (items ?? []).filter((r) => r.source !== "summary");
  if (researched.length === 0) {
    return (
      <div className="panel p-6 text-sm text-muted">
        No community research yet. Run{" "}
        <code className="text-accent">seismo community-research --source all</code> to collect
        discussion from GitHub, Hugging Face and Hacker News.
      </div>
    );
  }

  // Sources that actually surfaced discussion come first; empty/failed ones fold to a muted note.
  const found = researched.filter((r) => r.status === "found" && r.threads.length > 0);
  const empty = researched.filter((r) => !(r.status === "found" && r.threads.length > 0));

  return (
    <div className="space-y-2.5">
      {found.map((r) => (
        <div key={r.source} className="panel p-4">
          <div className="flex items-center gap-2">
            <span className="rounded-full border border-border px-2 py-0.5 text-[10px] uppercase tracking-wide text-accent">
              {SOURCE_LABEL[r.source] ?? r.source}
            </span>
            {r.confidence && (
              <span className="text-[11px] text-faint">{r.confidence} confidence</span>
            )}
            <span className="text-[11px] text-faint">· {shortDate(r.researched_at)}</span>
          </div>

          <p className="mt-2 text-[13px] leading-relaxed text-muted">{r.summary}</p>

          {r.main_points.length > 0 && (
            <ul className="mt-2 list-disc space-y-0.5 pl-4 text-[12px] text-muted">
              {r.main_points.map((p, i) => (
                <li key={i}>{p}</li>
              ))}
            </ul>
          )}

          <div className="mt-3 space-y-2.5">
            {r.threads.map((t, i) => (
              <ThreadRow key={i} thread={t} />
            ))}
          </div>
        </div>
      ))}

      {empty.length > 0 && (
        <div className="panel p-3 text-[12px] text-faint">
          No discussion found on{" "}
          {empty.map((r) => SOURCE_LABEL[r.source] ?? r.source).join(", ")}.
        </div>
      )}
    </div>
  );
}

function ThreadRow({ thread: t }: { thread: CommunityThread }) {
  return (
    <div className="rounded-lg border border-border p-3">
      <div className="flex items-start justify-between gap-3">
        <div className="min-w-0">
          <div className="flex flex-wrap items-center gap-2">
            <span className="text-[10px] uppercase tracking-wide text-faint">{t.channel}</span>
            {t.comment_count != null && (
              <span className="text-[11px] text-faint">{compactNum(t.comment_count)} comments</span>
            )}
            {t.score != null && t.score > 0 && (
              <span className="text-[11px] text-faint">· {compactNum(t.score)} pts</span>
            )}
          </div>
          {t.title && <div className="mt-1 truncate text-[13px] font-medium text-text">{t.title}</div>}
        </div>
        {t.url && (
          <a
            href={t.url}
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

      {t.comments.length > 0 && (
        <div className="mt-2 space-y-1.5">
          {t.comments.slice(0, 4).map((c, i) => (
            <p
              key={i}
              className="border-l-2 border-border pl-2.5 text-[12px] leading-relaxed text-muted line-clamp-3"
            >
              {c}
            </p>
          ))}
          {t.comments.length > 4 && (
            <p className="pl-2.5 text-[11px] text-faint">+{t.comments.length - 4} more comments — open the thread</p>
          )}
        </div>
      )}
    </div>
  );
}
