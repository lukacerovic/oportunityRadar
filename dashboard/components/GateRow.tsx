import Link from "next/link";
import { titleize } from "@/lib/format";
import type { GateDecisionItem } from "@/lib/types";

// Suppression reasons → how the audit page labels + colours them (doc 07 §3).
const REASON: Record<string, { label: string; color: string; blurb: string }> = {
  unmapped_reach: {
    label: "No map surface",
    color: "#F59E0B",
    blurb: "Its category touches no company in the exposure map — hard-excluded (A-6).",
  },
  card_pending: {
    label: "Card pending",
    color: "#38BDF8",
    blurb: "No comprehension card yet — the gate never briefs an un-summarised entity (A-12).",
  },
  budget: {
    label: "Below weekly cut",
    color: "#64748B",
    blurb: "Eligible and scored, but outside the top few for the week's budget.",
  },
};

export function GateRow({ d, tone }: { d: GateDecisionItem; tone: "pass" | "suppressed" }) {
  const c = d.components;
  const reason = c.reason ? REASON[c.reason] : null;
  return (
    <Link
      href={`/entity/${d.entity_id}`}
      className="panel flex flex-wrap items-center gap-x-5 gap-y-3 p-4 transition hover:bg-card-hover"
    >
      <div className="min-w-[180px] flex-1">
        <div className="flex items-center gap-2">
          <span className="truncate text-[15px] font-semibold">{d.name}</span>
          {reason && (
            <span
              className="shrink-0 rounded-full px-2 py-0.5 text-[10px] font-medium"
              style={{
                color: reason.color,
                background: `${reason.color}14`,
                border: `1px solid ${reason.color}33`,
              }}
              title={reason.blurb}
            >
              {reason.label}
            </span>
          )}
        </div>
        <div className="mt-1 text-xs text-muted">
          {titleize(d.category)} · {d.entity_type} · peaked{" "}
          <span className="text-faint">{c.peak_state ?? "—"}</span>
        </div>
      </div>

      <Factor label="M" value={c.M} hint="Momentum (peak state × velocity)" />
      <Factor
        label="R"
        value={c.R}
        hint={`Reach — ${c.reach_lines ?? 0} line(s)${c.reach_core ? ", core" : ""}`}
      />
      <Factor label="N" value={c.N} hint="Novelty (cohort pioneer proxy)" />

      <div className="w-[68px] text-right">
        <div className={`tabular text-lg font-semibold ${tone === "pass" ? "text-positive" : "text-text"}`}>
          {d.score.toFixed(2)}
        </div>
        <div className="text-[10px] uppercase tracking-wide text-faint">score</div>
      </div>
    </Link>
  );
}

function Factor({ label, value, hint }: { label: string; value: number | null; hint: string }) {
  return (
    <div className="w-[52px] text-center" title={hint}>
      <div className="tabular text-sm text-text">{value === null ? "—" : value.toFixed(2)}</div>
      <div className="text-[10px] uppercase tracking-wide text-faint">{label}</div>
    </div>
  );
}
