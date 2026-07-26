import type { CommunityResearch } from "@/lib/types";

// The cross-source AI verdict ("what does the community think?") — the entity_community_research
// row with source='summary'. Rendered as a right-column KPI panel below the Maturity Ladder.

const SENTIMENT_META: Record<string, { label: string; color: string }> = {
  positive: { label: "Positive", color: "#2DD4BF" },
  mostly_positive: { label: "Mostly Positive", color: "#4ADE80" },
  mixed: { label: "Mixed", color: "#FBBF24" },
  mostly_negative: { label: "Mostly Negative", color: "#FB923C" },
  negative: { label: "Negative", color: "#F87171" },
  insufficient_data: { label: "Not enough signal", color: "#64748B" },
};

function meta(sentiment: string | null) {
  return (sentiment && SENTIMENT_META[sentiment]) || SENTIMENT_META.insufficient_data;
}

export function CommunityVerdict({ items }: { items: CommunityResearch[] }) {
  const v = (items ?? []).find((r) => r.source === "summary");

  // No verdict yet, or nothing quotable was found across sources.
  if (!v || v.status !== "found") {
    return (
      <div className="panel p-4">
        <div className="label mb-2">Community Verdict</div>
        <p className="text-[12px] leading-relaxed text-faint">
          No AI verdict yet. Run{" "}
          <code className="text-accent">seismo community-research --source summary</code> after
          discussion has been collected.
        </p>
      </div>
    );
  }

  const m = meta(v.sentiment);
  const k = v.kpis;
  const hasScore = v.sentiment_score != null;

  return (
    <div className="panel p-4">
      <div className="mb-3 flex items-center justify-between">
        <div className="label">Community Verdict</div>
        {v.confidence && <span className="text-[10px] uppercase tracking-wide text-faint">{v.confidence} confidence</span>}
      </div>

      {/* Sentiment KPI */}
      <div className="flex items-end gap-3">
        {hasScore && (
          <div className="text-3xl font-semibold leading-none" style={{ color: m.color }}>
            {v.sentiment_score}
            <span className="text-base text-faint">/100</span>
          </div>
        )}
        <div className="pb-0.5">
          <span
            className="rounded-full px-2 py-0.5 text-[11px] font-medium"
            style={{ color: m.color, backgroundColor: `${m.color}1a` }}
          >
            {m.label}
          </span>
        </div>
      </div>

      {/* Engagement KPIs */}
      {k && (
        <div className="mt-3 flex flex-wrap gap-x-4 gap-y-1 text-[11px] text-muted">
          <span><span className="text-text">{k.thread_count}</span> threads</span>
          <span><span className="text-text">{k.comment_count}</span> comments</span>
          {k.sources.length > 0 && <span>{k.sources.join(" · ")}</span>}
        </div>
      )}

      <p className="mt-3 text-[12.5px] leading-relaxed text-muted">{v.summary}</p>

      {v.positive_signals.length > 0 && (
        <Section title="What people like" color="#4ADE80" items={v.positive_signals} />
      )}
      {v.concerns.length > 0 && (
        <Section title="Concerns" color="#FB923C" items={v.concerns} />
      )}

      {v.notable_quotes.length > 0 && (
        <blockquote className="mt-3 border-l-2 border-border pl-2.5 text-[12px] italic leading-relaxed text-faint">
          “{v.notable_quotes[0]}”
        </blockquote>
      )}
    </div>
  );
}

function Section({ title, color, items }: { title: string; color: string; items: string[] }) {
  return (
    <div className="mt-3">
      <div className="mb-1 text-[10px] uppercase tracking-wide" style={{ color }}>
        {title}
      </div>
      <ul className="space-y-0.5 text-[12px] text-muted">
        {items.slice(0, 4).map((it, i) => (
          <li key={i} className="flex gap-1.5">
            <span style={{ color }}>·</span>
            <span>{it}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}
