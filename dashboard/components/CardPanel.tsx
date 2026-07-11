import type { Card } from "@/lib/types";
import { titleize } from "@/lib/format";

// The comprehension card rendered like the reference "AI Summary": headline prose, then two
// co-equal sub-panels — the pitch (claimed_advantage + what it replaces) and the open questions
// (design encodes epistemics: what the evidence does NOT establish sits beside the pitch).
export function CardPanel({ card }: { card: Card | null }) {
  if (!card) {
    return (
      <div className="panel p-5 text-sm text-faint">
        No comprehension card yet — this entity hasn’t crossed the trigger (survived 7d with ≥2
        evidence types, a promotion, or staleness while warm).
      </div>
    );
  }
  const pending = card.status !== "ok";
  return (
    <div className="panel overflow-hidden">
      <div className="flex items-center justify-between border-b border-border-soft px-5 py-3">
        <div className="flex items-center gap-2.5">
          <span className="grid h-7 w-7 place-items-center rounded-md bg-accent/12 text-accent">
            <svg width="15" height="15" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="2">
              <path d="M12 3v3m0 12v3M3 12h3m12 0h3M5.6 5.6l2.1 2.1m8.6 8.6l2.1 2.1m0-12.8l-2.1 2.1M7.7 16.3l-2.1 2.1" strokeLinecap="round" />
            </svg>
          </span>
          <div>
            <div className="text-sm font-semibold">Comprehension Card</div>
            <div className="text-[11px] text-faint">
              v{card.version} · {card.model} · confidence {card.confidence ?? "—"}
            </div>
          </div>
        </div>
        <div className="flex items-center gap-2 text-[11px]">
          {card.category_disputed && (
            <span className="rounded-md border border-warn/40 bg-warn/10 px-2 py-0.5 text-warn">
              category disputed
            </span>
          )}
          {pending && (
            <span className="rounded-md border border-faint/40 px-2 py-0.5 text-muted">
              {card.status}
            </span>
          )}
        </div>
      </div>

      <div className="space-y-4 px-5 py-4">
        <p className="text-[15px] leading-relaxed text-text">
          {card.what_it_is ?? "—"}
        </p>
        {card.function && (
          <p className="text-sm leading-relaxed text-muted">
            <span className="text-faint">Function · </span>
            {card.function}
          </p>
        )}

        <div className="grid gap-3 md:grid-cols-2">
          <SubPanel title="The Pitch" tone="positive">
            <li>{card.claimed_advantage ?? "not established by evidence"}</li>
            {card.replaces_or_enables.map((r, i) => (
              <li key={i}>Replaces / enables: {r}</li>
            ))}
          </SubPanel>
          <SubPanel title="Open Questions" tone="warn">
            {card.open_questions.length ? (
              card.open_questions.map((q, i) => <li key={i}>{q}</li>)
            ) : (
              <li className="text-faint">None recorded.</li>
            )}
          </SubPanel>
        </div>

        <div className="flex flex-wrap gap-4 border-t border-border-soft pt-3 text-xs text-muted">
          <span>
            <span className="text-faint">Category · </span>
            {titleize(card.category)}
          </span>
          <span>
            <span className="text-faint">Behind · </span>
            {card.who_is_behind ?? "—"}
          </span>
        </div>
      </div>
    </div>
  );
}

function SubPanel({
  title,
  tone,
  children,
}: {
  title: string;
  tone: "positive" | "warn";
  children: React.ReactNode;
}) {
  const dot = tone === "positive" ? "#34D399" : "#F59E0B";
  const marker = tone === "positive" ? "marker:text-positive" : "marker:text-warn";
  return (
    <div className="rounded-lg border border-border-soft bg-surface/60 p-3.5">
      <div className="label mb-2" style={{ color: dot }}>
        {title}
      </div>
      <ul className={`list-disc space-y-1.5 pl-4 text-[13px] leading-snug text-muted ${marker}`}>
        {children}
      </ul>
    </div>
  );
}
